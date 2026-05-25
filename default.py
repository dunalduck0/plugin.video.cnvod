"""Kodi plugin entry point.

Routes:
    plugin://plugin.video.cnvod/                          -> root menu
    plugin://plugin.video.cnvod/?act=search               -> prompt + search both sites
    plugin://plugin.video.cnvod/?act=episodes&site=X&id=Y -> episode list for a series
    plugin://plugin.video.cnvod/?act=play&site=X&id=Y&ep=N -> resolve + play
"""

from __future__ import annotations

import sys
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

# Make `resources/lib/...` importable
import os
_addon_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_addon_dir, "resources", "lib"))

import history  # noqa: E402
from sites import PROVIDERS, StreamInfo, VideoResult  # noqa: E402


HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name") or "OleVod"
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))


def _enabled_providers():
    out = []
    for pid, p in PROVIDERS.items():
        setting = f"enable_{pid}"
        try:
            if ADDON.getSettingBool(setting):
                out.append(p)
        except Exception:
            # Default-on for olevod if setting doesn't exist yet
            if pid == "olevod":
                out.append(p)
    return out or list(PROVIDERS.values())[:1]


def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"[{ADDON_NAME}] {msg}", level)


def _url(**kwargs) -> str:
    return BASE_URL + "?" + urllib.parse.urlencode(
        {k: v for k, v in kwargs.items() if v is not None}
    )


def _notify(msg: str, icon: str = xbmcgui.NOTIFICATION_INFO) -> None:
    xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, 4000)


# -------------------- views --------------------

def view_root() -> None:
    item = xbmcgui.ListItem(label="[B]Search[/B]")
    item.setArt({"icon": "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(HANDLE, _url(act="search"), item, isFolder=True)

    recent = history.load(PROFILE_DIR)
    for q in recent:
        ri = xbmcgui.ListItem(label=q)
        ri.setArt({"icon": "DefaultAddonsSearch.png"})
        xbmcplugin.addDirectoryItem(
            HANDLE, _url(act="search", q=q), ri, isFolder=True
        )
    if recent:
        ci = xbmcgui.ListItem(label="[I]Clear search history[/I]")
        xbmcplugin.addDirectoryItem(
            HANDLE, _url(act="clear_history"), ci, isFolder=False
        )
    xbmcplugin.endOfDirectory(HANDLE)


def view_search(prefill: str = "") -> None:
    if prefill:
        query = prefill
    else:
        kb = xbmc.Keyboard("", "Search OleVod")
        kb.doModal()
        if not kb.isConfirmed():
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return
        query = kb.getText().strip()
    if not query:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    history.add(PROFILE_DIR, query)

    results: list[VideoResult] = []
    for provider in _enabled_providers():
        try:
            results.extend(provider.search(query))
        except Exception as e:  # noqa: BLE001
            _log(f"{provider.id} search failed: {e}", xbmc.LOGWARNING)
            _notify(f"{provider.name}: {e}", xbmcgui.NOTIFICATION_WARNING)

    if not results:
        _notify("No results")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    for r in results:
        label = f"[{r.site}] {r.title}"
        if r.subtitle:
            label += f" ({r.subtitle})"
        item = xbmcgui.ListItem(label=label)
        item.setArt({"thumb": r.thumbnail or "", "poster": r.thumbnail or ""})
        info = item.getVideoInfoTag()
        info.setTitle(r.title)
        if r.plot:
            info.setPlot(r.plot)
        # Always go through episodes view so the UX is uniform — even movies
        # have a single-entry "episode" list. This avoids guessing which
        # results are series vs movies in the search response.
        url = _url(act="episodes", site=r.site, id=r.id)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)

    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def view_episodes(site: str, video_id: str) -> None:
    provider = PROVIDERS.get(site)
    if not provider:
        _notify(f"Unknown site: {site}", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    try:
        episodes = provider.list_episodes(video_id)
    except Exception as e:  # noqa: BLE001
        _log(f"{site} episodes failed: {e}", xbmc.LOGERROR)
        _notify(str(e), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    if len(episodes) == 1:
        # Movie with a single stream: show it as a directly-playable item.
        # We MUST still call endOfDirectory (this is a directory handle), so
        # we add the single episode as a playable list item and let the user
        # click it — that triggers act=play on a fresh "resolve" handle where
        # setResolvedUrl works correctly.
        ep = episodes[0]
        item = xbmcgui.ListItem(label=ep.title)
        item.setProperty("IsPlayable", "true")
        url = _url(act="play", site=site, id=video_id, ep=ep.index)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)
        xbmcplugin.setContent(HANDLE, "videos")
        xbmcplugin.endOfDirectory(HANDLE)
        return

    for ep in episodes:
        item = xbmcgui.ListItem(label=ep.title)
        item.setProperty("IsPlayable", "true")
        url = _url(act="play", site=site, id=video_id, ep=ep.index)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)

    xbmcplugin.setContent(HANDLE, "episodes")
    xbmcplugin.endOfDirectory(HANDLE)


def play(site: str, video_id: str, episode: int = 1) -> None:
    provider = PROVIDERS.get(site)
    if not provider:
        _notify(f"Unknown site: {site}", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    try:
        info: StreamInfo = provider.resolve(video_id, episode)
    except Exception as e:  # noqa: BLE001
        _log(f"{site} resolve failed: {e}", xbmc.LOGERROR)
        _notify(str(e), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    item = xbmcgui.ListItem(label=info.title or video_id, path=info.url)
    if info.thumbnail:
        item.setArt({"thumb": info.thumbnail})

    # Use inputstream.adaptive for HLS so the Referer/UA headers actually
    # reach the CDN (otherwise olevod's europe.olemovienews.com returns 403).
    if info.is_hls:
        item.setProperty("inputstream", "inputstream.adaptive")
        # Kodi 19/20 uses inputstream.adaptive.manifest_type; Kodi 21+ ignores it.
        item.setProperty("inputstream.adaptive.manifest_type", "hls")
        if info.headers:
            hdrs = urllib.parse.urlencode(info.headers)
            item.setProperty("inputstream.adaptive.stream_headers", hdrs)
            item.setProperty("inputstream.adaptive.manifest_headers", hdrs)

    xbmcplugin.setResolvedUrl(HANDLE, True, item)


# -------------------- router --------------------

def _configure_providers() -> None:
    """Apply user settings to providers (e.g. VIP credentials for olevod)."""
    olevod = PROVIDERS.get("olevod")
    if not olevod:
        return
    try:
        username = ADDON.getSetting("olevod_username").strip()
        password = ADDON.getSetting("olevod_password").strip()
    except Exception:
        return
    if username and password:
        try:
            olevod.authenticate(username, password, PROFILE_DIR)
        except Exception as e:
            _log(f"olevod VIP login failed: {e}", xbmc.LOGWARNING)


def main() -> None:
    _configure_providers()
    qs = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    params = dict(urllib.parse.parse_qsl(qs))
    act = params.get("act")
    if not act:
        view_root()
    elif act == "search":
        view_search(params.get("q", ""))
    elif act == "clear_history":
        history.clear(PROFILE_DIR)
        _notify("Search history cleared")
        xbmc.executebuiltin("Container.Refresh")
    elif act == "episodes":
        view_episodes(params.get("site", ""), params.get("id", ""))
    elif act == "play":
        play(params.get("site", ""), params.get("id", ""), int(params.get("ep", "1")))
    else:
        view_root()


if __name__ == "__main__":
    main()
