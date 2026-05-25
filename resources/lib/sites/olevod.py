"""olevod.com extractor.

Clean-room reverse-engineered from the live JS bundle
(https://www.olevod.com/js/tv-pc-main.*.js):

* API host: https://api.olelive.com
* Every GET request gets a `_vv` query param signed from the current unix
  timestamp by the JS function `fe(t)`. See `_vv()` for the algorithm.
* The detail endpoint returns plain JSON. No AES decryption needed
  (as of November 2025; if olevod changes this in future, this module
  is where to patch).

Endpoints used:
    /v1/pub/index/search/{q}/0/0/0/1     -> search
    /v1/pub/vod/detail/{id}/true         -> detail (incl. play urls)

Static assets (thumbnails) live under https://static.olelive.com/.

The play URL is a master HLS playlist served by europe.olemovienews.com
and REQUIRES the Referer header `https://www.olevod.com/` to be sent.
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse

import requests

from .base import Episode, SiteProvider, StreamInfo, VideoResult

API = "https://api.olelive.com"
WEB = "https://www.olevod.com"
STATIC = "https://static.olelive.com/"
DEFAULT_TIMEOUT = 15

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


def _get(path: str, params: dict | None = None) -> dict:
    p = dict(params or {})
    p["_vv"] = _vv(int(time.time()))
    url = f"{API}{path}"
    r = requests.get(url, params=p, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"olevod API error: code={j.get('code')} msg={j.get('msg')}")
    return j.get("data") or {}


def _full_pic(pic: str | None) -> str | None:
    if not pic:
        return None
    if pic.startswith("http"):
        return pic
    return STATIC + pic.lstrip("/")


class OleVod(SiteProvider):
    id = "olevod"
    name = "OleVOD"

    def search(self, query: str) -> list[VideoResult]:
        q = urllib.parse.quote(query)
        data = _get(f"/v1/pub/index/search/{q}/0/0/0/1")
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
        return _get(f"/v1/pub/vod/detail/{video_id}/true")

    def list_episodes(self, video_id: str) -> list[Episode]:
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
