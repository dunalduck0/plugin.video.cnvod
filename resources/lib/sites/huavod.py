"""huavod.com (华视影院) extractor.

Site architecture (MaCMS-based):
    Search : GET /vodsearch.html?wd=<query>
             → HTML; parse /voddetail/<id>.html links for video IDs + thumbnails

    Detail : GET /voddetail/<id>.html
             → HTML; parse /vodplay/<id>-1-<ep>.html links for episode list
               (source 1 = "高性能"/ARTA player; we ignore other sources)

    Resolve: Two-step:
        1. GET /vodplay/<id>-1-<ep_num>.html
           → extract mac_player_info JSON (contains encoded url + vod_name)
        2. GET https://newplayer.huavod.com/player/ec.php?code=ok&url=<encoded>&tittle=<name>
           → extract window.HR_P2P.channel_key → HLS m3u8 URL

The mac_player_info.url is a server-opaque encoded string; ec.php decodes it
server-side and returns the real CDN URL in the HR_P2P object. No client-side
decryption needed.
"""

from __future__ import annotations

import json
import re

import requests

from .base import Episode, SiteProvider, StreamInfo, VideoResult

BASE_URL = "https://www.huavod.com"
PLAYER_BASE = "https://newplayer.huavod.com/player"
DEFAULT_TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL + "/",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _get(url: str, **kwargs) -> requests.Response:
    r = requests.get(url, headers=_HEADERS, timeout=DEFAULT_TIMEOUT, **kwargs)
    r.raise_for_status()
    return r


def _extract_json(html: str, var_name: str) -> dict:
    """Extract a JS object literal assigned to var_name using a JSON decoder.

    Uses raw_decode() so it cleanly stops at the end of the JSON object
    regardless of what follows (no semicolon required, no greedy/lazy issues).
    Handles optional whitespace around the '=' sign.
    """
    m = re.search(re.escape(var_name) + r'\s*=\s*\{', html)
    if not m:
        raise RuntimeError(f"huavod: '{var_name}' not found in page")
    # raw_decode starts at the '{' that opened the object
    start = m.end() - 1
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(html, start)
    return obj


class HuaVod(SiteProvider):
    id = "huavod"
    name = "HuaVod"

    def search(self, query: str) -> list[VideoResult]:
        url = BASE_URL + "/vodsearch.html"
        resp = _get(url, params={"wd": query})
        html = resp.text

        out: list[VideoResult] = []
        # Split by each search result block to parse them independently.
        # Structure of each block:
        #   <div class="thumb-txt ..."><a href="/voddetail/<id>.html">TITLE</a></div>
        #   <img ... alt="TITLE封面图" ... data-src="THUMB_URL">
        #   <span class="public-list-prb ...">BADGE</span>
        blocks = re.split(r'class="public-list-box\s+search-box', html)[1:]
        for block in blocks:
            vid_m = re.search(r'href="/voddetail/(\d+)\.html"', block)
            if not vid_m:
                continue
            vod_id = vid_m.group(1)

            # Title: inside <div class="thumb-txt ..."><a>TITLE</a></div>
            title_m = re.search(
                r'class="thumb-txt[^"]*"[^>]*>\s*<a[^>]+>([^<]+)</a>', block
            )
            # Fallback: use alt text from the cover image
            if not title_m:
                title_m = re.search(r'alt="([^"]+)封面图"', block)
            title = title_m.group(1).strip() if title_m else vod_id

            thumb_m = re.search(r'data-src="(https?://[^"]+)"', block)
            thumbnail = thumb_m.group(1) if thumb_m else None

            # Quality badge (e.g. "HD", "已完结", "正片", "TC")
            badge_m = re.search(r'class="public-list-prb[^"]*">([^<]+)<', block)
            subtitle = badge_m.group(1).strip() if badge_m else ""

            # Plot: the blurb/description at the bottom of the block
            plot_m = re.search(r'class="thumb-blurb[^"]*">([^<]+)<', block)
            plot = plot_m.group(1).strip() if plot_m else ""

            out.append(
                VideoResult(
                    site=self.id,
                    id=vod_id,
                    title=title,
                    subtitle=subtitle,
                    thumbnail=thumbnail,
                    plot=plot,
                )
            )
        return out

    def list_episodes(self, video_id: str) -> list[Episode]:
        url = BASE_URL + f"/voddetail/{video_id}.html"
        html = _get(url).text

        # Find the FIRST anthology-list-play block (source 1 = ARTA player).
        # The HTML has multiple anthology-list-box divs, one per source.
        ul_m = re.search(r'class="anthology-list-play size">(.*?)</ul>', html, re.DOTALL)
        if not ul_m:
            return [Episode(index=1, title="播放", url=video_id)]

        ep_links = re.findall(
            r'href="/vodplay/\d+-\d+-(\d+)\.html">([^<]+)<', ul_m.group(1)
        )
        if not ep_links:
            return [Episode(index=1, title="播放", url=video_id)]

        return [
            Episode(index=int(ep_num), title=ep_title.strip(), url=video_id)
            for ep_num, ep_title in ep_links
        ]

    def resolve(self, video_id: str, episode_index: int = 1) -> StreamInfo:
        # Step 1: fetch the play page and extract mac_player_info
        play_url = BASE_URL + f"/vodplay/{video_id}-1-{episode_index}.html"
        html = _get(play_url).text

        try:
            info = _extract_json(html, "mac_player_info")
        except Exception as exc:
            raise RuntimeError(f"huavod: could not extract mac_player_info: {exc}") from exc

        encoded_url = info.get("url", "")
        if not encoded_url:
            raise RuntimeError("huavod: no url in mac_player_info")

        vod_name = (info.get("vod_data") or {}).get("vod_name") or ""
        from_tag = info.get("from", "")

        # Step 2: if this is an ART* or DPA* player, resolve via ec.php
        code = "qw" if from_tag.upper().startswith("DP") else "ok"
        if from_tag.upper().startswith("ART") or from_tag.upper().startswith("DP"):
            m3u8_url = self._resolve_ec(encoded_url, vod_name, code=code)
            # cdnhr.b-cdn.net is a P2P-only CDN — probe it and raise a clear error
            # rather than returning a URL that Kodi will silently fail to open.
            if "b-cdn.net" in m3u8_url:
                try:
                    probe = _get(m3u8_url)
                    if probe.status_code >= 400:
                        raise RuntimeError(
                            "huavod: stream uses P2P-only CDN, not playable in Kodi"
                        )
                except RuntimeError:
                    raise
                except Exception:
                    raise RuntimeError(
                        "huavod: stream uses P2P-only CDN, not playable in Kodi"
                    )
            return StreamInfo(
                url=m3u8_url,
                headers={
                    "Referer": PLAYER_BASE + "/",
                    "User-Agent": _HEADERS["User-Agent"],
                },
                title=vod_name,
                is_hls=True,
            )

        # Fallback: treat url as a direct stream (encrypt=0 plain URL case)
        if encoded_url.startswith("http"):
            return StreamInfo(
                url=encoded_url,
                headers={
                    "Referer": BASE_URL + "/",
                    "User-Agent": _HEADERS["User-Agent"],
                },
                title=vod_name,
                is_hls=encoded_url.endswith(".m3u8"),
            )

        raise RuntimeError(
            f"huavod: unsupported player type '{from_tag}' — cannot resolve stream"
        )

    def _resolve_ec(self, encoded_url: str, title: str, code: str = "ok") -> str:
        """Fetch ec.php and extract the HLS URL from window.HR_P2P.channel_key."""
        ec_url = PLAYER_BASE + "/ec.php"
        params = {"code": code, "url": encoded_url, "tittle": title}
        resp = _get(ec_url, params=params)
        html = resp.text

        # window.HR_P2P = {...,"channel_key":"https://...m3u8",...};
        try:
            p2p = _extract_json(html, "window.HR_P2P")
        except Exception as exc:
            raise RuntimeError(f"huavod: could not extract HR_P2P: {exc}") from exc

        channel_key = p2p.get("channel_key", "")
        if not channel_key or not channel_key.startswith("http"):
            raise RuntimeError("huavod: empty or invalid channel_key in HR_P2P")
        return channel_key
