"""olevod.com extractor.

Clean-room reverse-engineered from the live JS bundle
(https://www.olevod.com/js/tv-pc-main.*.js):

* API host: https://api.olelive.com
* Every GET request gets a `_vv` query param signed from the current unix
  timestamp by the JS function `fe(t)`. See `_vv()` for the algorithm.
* Authenticated requests add _he/_pl/_si params derived from the login token.
* The detail endpoint returns plain JSON when unauthenticated; when authenticated
  the API *may* return an AES-encrypted `data` string (daily key, AES-CBC).
  See `_aes_decrypt()` for the algorithm.

Endpoints used:
    /v1/pub/index/search/{q}/0/0/0/1     -> search
    /v1/pub/vod/detail/{id}/true         -> detail (incl. play urls)
    /v1/pub/user/login                   -> login (POST)

Static assets (thumbnails) live under https://static.olelive.com/.

The play URL is a master HLS playlist served by europe.olemovienews.com
and REQUIRES the Referer header `https://www.olevod.com/` to be sent.

VIP login:
    Key  = md5(YYYY-MM-DD)[8:24]   (16-char substring, rotates daily)
    IV   = same as key
    Mode = AES-CBC, PKCS7 padding
    Token (returned by /login) is "aaa.bbb.ccc"; split by '.' and add as
    _he=aaa&_pl=bbb&_si=ccc to every authenticated request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime
from typing import Callable

import requests

from .base import Episode, SiteProvider, StreamInfo, VideoResult

API = "https://api.olelive.com"
WEB = "https://www.olevod.com"
STATIC = "https://static.olelive.com/"
DEFAULT_TIMEOUT = 15
# Re-login if cached token is older than this many seconds
TOKEN_TTL = 7 * 24 * 3600  # 7 days

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": WEB,
    "Referer": WEB + "/",
    "Accept": "application/json, text/plain, */*",
}

PLAYBACK_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": WEB + "/",
    "Origin": WEB,
}


def _vv(ts: int) -> str:
    """Sign a unix-seconds timestamp the way olevod's JS does.

    Equivalent JS:
        function he(c){return c.charCodeAt().toString(2)}
        function fe(e){
          let t=e.toString(), r=[[],[],[],[]];
          for(let c of t){ let b=he(c);
            r[0]+=b[2:3]; r[1]+=b[3:4]; r[2]+=b[4:5]; r[3]+=b[5:]; }
          // each r[i] -> hex, left-padded to 3 chars
          let n=md5(t);
          return n[0:3]+a[0]+n[6:11]+a[1]+n[14:19]+a[2]+n[22:27]+a[3]+n[30:]
        }
    """
    t = str(ts)
    cols = ["", "", "", ""]
    for ch in t:
        b = bin(ord(ch))[2:]  # digits 0-9 -> 6-bit binary "110000".."111001"
        cols[0] += b[2:3]
        cols[1] += b[3:4]
        cols[2] += b[4:5]
        cols[3] += b[5:]
    pieces = []
    for s in cols:
        hx = format(int(s, 2), "x") if s else ""
        # left-pad to 3 chars exactly
        if len(hx) == 2:
            hx = "0" + hx
        elif len(hx) == 1:
            hx = "00" + hx
        elif len(hx) == 0:
            hx = "000"
        pieces.append(hx)
    n = hashlib.md5(t.encode()).hexdigest()
    return (
        n[0:3] + pieces[0] + n[6:11] + pieces[1]
        + n[14:19] + pieces[2] + n[22:27] + pieces[3] + n[30:]
    )


def _aes_daily_key() -> bytes:
    """Return the 16-byte AES key for today (local date).

    JS: D(YYYY-MM-DD).substring(8, 24)  where D = md5
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    return hashlib.md5(date_str.encode()).hexdigest()[8:24].encode()


def _aes_decrypt(ciphertext: str) -> str | None:
    """Decrypt an AES-CBC / PKCS7 / base64 ciphertext from olevod API.

    Returns the plaintext string, or None if decryption is unavailable or fails.
    """
    try:
        from Crypto.Cipher import AES  # type: ignore[import]
        from Crypto.Util.Padding import unpad  # type: ignore[import]
        key = _aes_daily_key()
        cipher = AES.new(key, AES.MODE_CBC, iv=key)
        decoded = base64.b64decode(ciphertext)
        plaintext = unpad(cipher.decrypt(decoded), AES.block_size)
        return plaintext.decode("utf-8")
    except Exception:
        return None


def _get(path: str, params: dict | None = None, token: str | None = None) -> dict:
    p = dict(params or {})
    p["_vv"] = _vv(int(time.time()))
    if token:
        parts = token.split(".")
        if len(parts) == 3:
            p["_he"], p["_pl"], p["_si"] = parts
    url = f"{API}{path}"
    r = requests.get(url, params=p, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    code = j.get("code")
    if code == 13 or code == 14:
        # Auth error — token expired / invalid
        raise AuthError(f"olevod auth error: code={code} msg={j.get('msg')}")
    if code != 0:
        raise RuntimeError(f"olevod API error: code={code} msg={j.get('msg')}")
    data = j.get("data")
    # If data is an encrypted string (AES-CBC), decrypt it
    if isinstance(data, str) and data:
        decrypted = _aes_decrypt(data)
        if decrypted:
            return json.loads(decrypted)
    return data or {}


def _full_pic(pic: str | None) -> str | None:
    if not pic:
        return None
    if pic.startswith("http"):
        return pic
    return STATIC + pic.lstrip("/")


def _load_token(profile_dir: str, username: str) -> str | None:
    """Load cached token; return None if missing, expired, or for different user."""
    try:
        path = os.path.join(profile_dir, "olevod_token.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("username") != username:
            return None
        if time.time() - float(d.get("saved_at", 0)) > TOKEN_TTL:
            return None
        return d.get("token")
    except Exception:
        return None


def _save_token(profile_dir: str, username: str, token: str) -> None:
    try:
        os.makedirs(profile_dir, exist_ok=True)
        path = os.path.join(profile_dir, "olevod_token.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"username": username, "token": token, "saved_at": time.time()}, f)
    except Exception:
        pass


def _fetch_captcha() -> tuple[str, str]:
    """Fetch a captcha from the API.

    Returns (captcha_id, base64_image_data) where base64_image_data is the
    raw base64 string (without the data:image/png;base64, prefix).
    """
    r = requests.post(
        f"{API}/pub/captcha",
        json={},
        params={"_vv": _vv(int(time.time()))},
        headers=HEADERS,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    d = r.json().get("data", {})
    captcha_id = d.get("captchaId", "")
    pic_path = d.get("picPath", "")
    # picPath is "data:image/png;base64,<data>"
    b64 = pic_path.split(",", 1)[1] if "," in pic_path else pic_path
    return captcha_id, b64


def _do_login(username: str, password: str, captcha: str, captcha_id: str) -> str:
    """POST to login endpoint and return the token string."""
    r = requests.post(
        f"{API}/pub/user/login",
        json={"username": username, "password": password,
              "captcha": captcha, "captcha_id": captcha_id},
        params={"_vv": _vv(int(time.time()))},
        headers=HEADERS,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"olevod login failed: {j.get('msg', 'unknown error')}")
    token = j.get("data", {}).get("token")
    if not token:
        raise RuntimeError("olevod login: no token in response")
    return token


class AuthError(Exception):
    pass


class OleVod(SiteProvider):
    id = "olevod"
    name = "OleVOD"

    def __init__(self) -> None:
        self._token: str | None = None

    def authenticate(self, username: str, password: str, profile_dir: str,
                     ask_captcha: "Callable[[str, str], str] | None" = None) -> None:
        """Load or refresh the VIP login token.

        Called by default.py at startup when credentials are configured.
        ask_captcha(captcha_id, image_b64) -> captcha_text  (callable provided by Kodi UI)
        If ask_captcha is None and no cached token exists, raises RuntimeError.
        """
        token = _load_token(profile_dir, username)
        if not token:
            if ask_captcha is None:
                raise RuntimeError("olevod: no cached token and no captcha handler provided")
            captcha_id, image_b64 = _fetch_captcha()
            captcha_text = ask_captcha(captcha_id, image_b64)
            if not captcha_text:
                raise RuntimeError("olevod: captcha not entered")
            token = _do_login(username, password, captcha_text, captcha_id)
            _save_token(profile_dir, username, token)
        self._token = token

    def _api_get(self, path: str, params: dict | None = None) -> dict:
        """Wrapper that injects auth token and retries login on auth error."""
        try:
            return _get(path, params, self._token)
        except AuthError:
            # Token expired — clear it; caller should re-login next invocation
            self._token = None
            raise

    def search(self, query: str) -> list[VideoResult]:
        q = urllib.parse.quote(query)
        data = self._api_get(f"/v1/pub/index/search/{q}/0/0/0/1")
        out: list[VideoResult] = []
        for group in data.get("data") or []:
            items = group.get("list") or []
            for it in items:
                out.append(
                    VideoResult(
                        site=self.id,
                        id=str(it.get("id")),
                        title=it.get("name") or "",
                        subtitle=it.get("remarks") or "",
                        thumbnail=_full_pic(it.get("pic")),
                        plot=it.get("blurb") or "",
                    )
                )
        return out

    def _detail(self, video_id: str) -> dict:
        return self._api_get(f"/v1/pub/vod/detail/{video_id}/true")

    def list_episodes(self, video_id: str) -> list[Episode]:
        if video_id.startswith("live:"):
            # Sports/live items are single-stream — synthesise one episode.
            return [Episode(index=1, title="回放", url=video_id)]
        d = self._detail(video_id)
        return [
            Episode(
                index=int(u.get("index") or i + 1),
                title=u.get("title") or f"#{i+1}",
                url=u.get("url") or "",
            )
            for i, u in enumerate(d.get("urls") or [])
        ]

    def resolve(self, video_id: str, episode_index: int = 1) -> StreamInfo:
        if video_id.startswith("live:"):
            return self._resolve_live(video_id)
        d = self._detail(video_id)
        urls = d.get("urls") or []
        if not urls:
            raise RuntimeError("olevod: no playable URLs in response")
        # episode_index is 1-based, match against `index` then fall back to position
        chosen = next(
            (u for u in urls if int(u.get("index") or 0) == episode_index),
            urls[episode_index - 1] if 0 < episode_index <= len(urls) else urls[0],
        )
        return StreamInfo(
            url=chosen.get("url") or "",
            headers=dict(PLAYBACK_HEADERS),
            title=f"{d.get('name','')} - {chosen.get('title','')}".strip(" -"),
            thumbnail=_full_pic(d.get("pic")),
            is_hls=True,
        )

    # -------------------- 赛事直播 (sports live) --------------------

    def list_sports(self, count: int = 12) -> list[VideoResult]:
        """Return the latest matches from the home-page 赛事直播 carousel.

        Each result's id is `live:{match_id}:{stream_id}` so resolve() can
        route it to the live API instead of the regular vod/detail path.
        """
        data = self._api_get(f"/v1/pub/index/lives/live/0/0/{count}")
        items = data if isinstance(data, list) else (data.get("data") or [])
        out: list[VideoResult] = []
        for it in items:
            mid = it.get("id")
            stream = it.get("streamId") or ""
            if not mid or not stream:
                continue
            title = it.get("title") or ""
            mt = it.get("matchTime") or ""
            # "VIP" flag isn't on this payload, but liveHasVod indicates replay
            # is available. liveAlive indicates a live broadcast in progress.
            status = "🔴 直播" if it.get("liveAlive") else ("回放" if it.get("liveHasVod") else "预告")
            out.append(
                VideoResult(
                    site=self.id,
                    id=f"live:{mid}:{stream}",
                    title=title,
                    subtitle=f"{status} · {mt}".strip(" ·"),
                    thumbnail=it.get("currentImg") or None,
                    plot=f"{it.get('homeName','')} vs {it.get('awayName','')}".strip(" vs"),
                )
            )
        return out

    def _resolve_live(self, composite_id: str) -> StreamInfo:
        # composite_id = "live:{id}:{streamId}"
        parts = composite_id.split(":", 2)
        if len(parts) != 3:
            raise RuntimeError(f"olevod: malformed live id {composite_id!r}")
        _, mid, stream = parts
        data = self._api_get(f"/v1/pub/live/info/live/{mid}/{stream}/0")
        detail = (data or {}).get("detail") or {}
        url = detail.get("hls") or detail.get("flv") or ""
        if not url:
            if detail.get("liveAlive") is False and detail.get("liveHasVod") is False:
                raise RuntimeError("olevod: 比赛尚未开始 (match has not started)")
            raise RuntimeError("olevod: no playable URL for this match")
        title = detail.get("title") or ""
        if detail.get("homeName") and detail.get("awayName"):
            title = f"{detail['homeName']} vs {detail['awayName']}"
        return StreamInfo(
            url=url,
            headers=dict(PLAYBACK_HEADERS),
            title=title,
            thumbnail=detail.get("livingBreakImg") or None,
            is_hls=True,
        )
