"""iyf.tv extractor.

Signing algorithm (clean-room RE from main.*.js at https://www.iyf.tv):

    publicKey, privateKey = window.pConfig.pConfig.{publicKey,privateKey[0]}
    vv = md5(publicKey + "&" + query_string_lowercased + "&" + privateKey)
    Every signed request appends: &vv=<vv>&pub=<publicKey>

Keys are session-specific and are fetched once per addon call from the HTML
page. They rotate per-request on the server but a single fresh fetch is enough
for one signing operation.

Endpoints:
    GET https://rankv21.iyf.tv/v3/list/briefsearch  -> search
    GET https://m10.iyf.tv/v3/video/play            -> stream resolution (vv validated)

video_id format: "<contxt>" — the series/video level key from search results.

For series the play API returns the first/default episode stream. Per-episode
selection requires individual episode contxt keys which are not included in
the search result; full episode-list support is left as a future enhancement.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse

import requests

from .base import Episode, SiteProvider, StreamInfo, VideoResult

CINEMA = 1
WEB = "https://www.iyf.tv"
API_PLAY = "https://m10.iyf.tv/v3/video/play"
API_SEARCH = "https://rankv21.iyf.tv/v3/list/briefsearch"
DEFAULT_TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": WEB + "/",
    "Accept": "application/json, text/plain, */*",
}

# Module-level key cache; valid for the lifetime of one Kodi plugin call.
_cached_keys: tuple[str, str] | None = None


def _fetch_keys() -> tuple[str, str]:
    """Return (publicKey, privateKey) from window.pConfig in the iyf.tv HTML."""
    r = requests.get(WEB + "/", headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    m = re.search(
        r'"pConfig":\{"publicKey":"([^"]+)","privateKey":\["([^"]+)"\]\}',
        r.text,
    )
    if not m:
        raise RuntimeError("iyf.tv: could not extract signing keys from page")
    return m.group(1), m.group(2)


def _get_keys() -> tuple[str, str]:
    global _cached_keys
    if _cached_keys is None:
        _cached_keys = _fetch_keys()
    return _cached_keys


def _sign(base_url: str, params: dict) -> str:
    """Build a signed URL by appending vv and pub to the query string.

    Sign input mirrors the JS uriSignature():
        pub + "&" + raw_query_lowercased + "&" + priv
    where raw_query is built from the *unencoded* values (mimicking JS
    get_query(url) which URL-decodes the values before signing).
    The actual request URL uses urllib.parse.urlencode for proper encoding.
    """
    pub, priv = _get_keys()
    # Sign with unencoded values (matches JS get_query → toLowerCase behaviour)
    raw_qs = "&".join(f"{k}={v}" for k, v in params.items())
    sign_input = pub + "&" + raw_qs.lower() + "&" + priv
    vv = hashlib.md5(sign_input.encode()).hexdigest()
    encoded_qs = urllib.parse.urlencode(params)
    return f"{base_url}?{encoded_qs}&vv={vv}&pub={pub}"


def _api_get(base_url: str, params: dict) -> dict:
    url = _sign(base_url, params)
    r = requests.get(url, headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    data = j.get("data") or {}
    if isinstance(data, dict) and data.get("code") not in (0, None):
        raise RuntimeError(
            f"iyf.tv API error: code={data.get('code')} msg={data.get('msg', '')}"
        )
    return data


class IyfTv(SiteProvider):
    id = "iyftv"
    name = "iyf.tv"

    def search(self, query: str) -> list[VideoResult]:
        # Param order matches JS urlBuilder output for "solr-search" route
        params = {"cinema": CINEMA, "tags": query, "page": 1, "size": 20}
        data = _api_get(API_SEARCH, params)
        info_list = data.get("info") or []
        if not info_list:
            return []

        out: list[VideoResult] = []
        for item in info_list[0].get("result") or []:
            contxt = item.get("contxt") or ""
            if not contxt:
                continue
            play_list = (
                (item.get("languagesPlayList") or {}).get("playList") or []
            )
            ep_count = len(play_list)
            out.append(
                VideoResult(
                    site=self.id,
                    id=contxt,
                    title=item.get("title") or "",
                    subtitle=item.get("lastName") or "",
                    thumbnail=item.get("imgPath") or None,
                    plot=(item.get("starring") or "").replace(",", " · "),
                    is_series=ep_count > 1,
                    episode_count=ep_count,
                )
            )
        return out

    def list_episodes(self, video_id: str) -> list[Episode]:
        # video_id is the series/content contxt key.
        # The play API returns a stream for the contxt key (typically EP1/default).
        # Per-episode selection is not yet supported; all episodes resolve via contxt.
        return [Episode(index=1, title="Play", url=video_id)]

    def resolve(self, video_id: str, episode_index: int = 1) -> StreamInfo:
        # video_id is always the contxt key — use it directly as the API id.
        # Param order must match JS urlBuilder for "video-media" route so that
        # the vv signature is computed over the same query string the server expects.
        params = {
            "cinema": CINEMA,
            "id": video_id,
            "a": 1,
            "lang": "none",
            "usersign": 1,
            "region": "US",
            "device": 1,
            "isMasterSupport": 1,
        }
        data = _api_get(API_PLAY, params)
        streams = ((data.get("info") or [{}])[0]).get("flvPathList") or []
        if not streams:
            raise RuntimeError("iyf.tv: no streams in API response")

        hls = next((s for s in streams if s.get("isHls")), None)
        mp4 = next((s for s in streams if not s.get("isHls")), None)
        chosen = hls or mp4
        if not chosen or not chosen.get("result"):
            raise RuntimeError("iyf.tv: no playable stream URL found")

        return StreamInfo(
            url=chosen["result"],
            headers={"Referer": WEB + "/", "User-Agent": _HEADERS["User-Agent"]},
            is_hls=bool(chosen.get("isHls")),
        )
