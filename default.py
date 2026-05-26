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


def _notify(msg: str, icon: str = xbmcgui.NOTIFICATION_INFO, time: int = 4000) -> None:
    xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, time)


# -------------------- views --------------------

def view_root() -> None:
    item = xbmcgui.ListItem(label="[B]Search[/B]")
    item.setArt({"icon": "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(HANDLE, _url(act="search"), item, isFolder=True)

    # Show login status / account entry
    olevod = PROVIDERS.get("olevod")
    if olevod and hasattr(olevod, "_token") and olevod._token:
        acct_label = "[COLOR green]✓ OleVOD VIP logged in[/COLOR]"
    else:
        username = ""
        try:
            username = ADDON.getSetting("olevod_username").strip()
        except Exception:
            pass
        if username:
            acct_label = "[COLOR yellow]⚠ OleVOD VIP — tap to login[/COLOR]"
        else:
            acct_label = "[COLOR grey]OleVOD VIP — tap to set credentials[/COLOR]"
    acct_item = xbmcgui.ListItem(label=acct_label)
    acct_item.setArt({"icon": "DefaultAddonProgram.png"})
    xbmcplugin.addDirectoryItem(HANDLE, _url(act="vip_login"), acct_item, isFolder=False)

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


def view_vip_login() -> None:
    """Interactive VIP login: prompt for username, password, then captcha."""
    # Step 1: username
    cur_user = ""
    try:
        cur_user = ADDON.getSetting("olevod_username").strip()
    except Exception:
        pass
    kb_user = xbmc.Keyboard(cur_user, "OleVOD Username / Email")
    kb_user.doModal()
    if not kb_user.isConfirmed() or not kb_user.getText().strip():
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    username = kb_user.getText().strip()

    # Step 2: password
    cur_pass = ""
    try:
        cur_pass = ADDON.getSetting("olevod_password").strip()
    except Exception:
        pass
    kb_pass = xbmc.Keyboard(cur_pass, "OleVOD Password")
    kb_pass.setHiddenInput(True)
    kb_pass.doModal()
    if not kb_pass.isConfirmed() or not kb_pass.getText().strip():
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    password = kb_pass.getText().strip()

    # Save credentials to settings
    ADDON.setSetting("olevod_username", username)
    ADDON.setSetting("olevod_password", password)

    # Step 3: fetch captcha image, show it, ask user to type it
    def _ask_captcha(captcha_id: str, image_b64: str) -> str:
        import base64
        captcha_path = os.path.join(PROFILE_DIR, "captcha.png")
        try:
            os.makedirs(PROFILE_DIR, exist_ok=True)
            with open(captcha_path, "wb") as f:
                f.write(base64.b64decode(image_b64))
        except Exception:
            captcha_path = ""
        if captcha_path:
            xbmc.executebuiltin(f"ShowPicture({captcha_path})")
            xbmc.sleep(1500)
        kb = xbmc.Keyboard("", "Enter captcha characters")
        kb.doModal()
        if captcha_path:
            xbmc.executebuiltin("Action(Back)")
        return kb.getText().strip() if kb.isConfirmed() else ""

    olevod = PROVIDERS.get("olevod")
    try:
        olevod.authenticate(username, password, PROFILE_DIR, ask_captcha=_ask_captcha)
        _notify("OleVOD VIP login successful ✓")
    except Exception as e:
        msg = str(e)
        _log(f"olevod VIP login failed: {msg}", xbmc.LOGWARNING)
        if "502" in msg or "503" in msg or "Bad Gateway" in msg:
            friendly = "OleVOD login: server unavailable, try again later"
        elif "captcha" in msg.lower():
            friendly = "OleVOD login: captcha failed, try again"
        else:
            friendly = f"OleVOD login failed: {msg[:80]}"
        _notify(friendly, xbmcgui.NOTIFICATION_WARNING)
    xbmc.executebuiltin("Container.Refresh")
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


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
            # inputstream.adaptive expects "Key=Value&Key2=Value2" — NOT percent-encoded
            hdrs = "&".join(f"{k}={v}" for k, v in info.headers.items())
            item.setProperty("inputstream.adaptive.stream_headers", hdrs)
            item.setProperty("inputstream.adaptive.manifest_headers", hdrs)

    xbmcplugin.setResolvedUrl(HANDLE, True, item)


# -------------------- router --------------------

def _configure_providers() -> None:
    """Load cached VIP token silently at startup — never prompts for captcha."""
    olevod = PROVIDERS.get("olevod")
    if not olevod:
        return
    try:
        username = ADDON.getSetting("olevod_username").strip()
        password = ADDON.getSetting("olevod_password").strip()
    except Exception:
        return
    if not username or not password:
        return
    try:
        # ask_captcha=None: only loads a cached token, never prompts
        olevod.authenticate(username, password, PROFILE_DIR, ask_captcha=None)
        _log("olevod: cached token loaded")
    except RuntimeError:
        # Credentials set but no cached token — guide user to VIP Login item
        _notify("OleVOD: tap 'VIP Login' in the menu to complete login",
                xbmcgui.NOTIFICATION_INFO, time=6000)
    except Exception as e:
        _log(f"olevod token load failed: {e}", xbmc.LOGWARNING)


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
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    elif act == "vip_login":
        view_vip_login()
    elif act == "episodes":
        view_episodes(params.get("site", ""), params.get("id", ""))
    elif act == "play":
        play(params.get("site", ""), params.get("id", ""), int(params.get("ep", "1")))
    else:
        view_root()


if __name__ == "__main__":
    main()
