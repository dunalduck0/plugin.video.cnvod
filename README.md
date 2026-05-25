# OleVod — Kodi Addon

Search and stream Chinese on-demand video sites (**olevod.com**, **iyf.tv**) directly inside Kodi — no PC, no DevTools, no `.strm` file shuffling.

## Status

| Site | Search | Play |
| --- | --- | --- |
| olevod.com | ✅ | ✅ (movies + multi-episode series) |
| iyf.tv | ⛔ Phase 2 | ⛔ Phase 2 |

iyf.tv signing is reverse-engineered separately and will be wired in once captured.

## Install on Kodi (TV or desktop)

1. Settings → System → Add-ons → enable **Unknown sources**
2. Grab the latest zip from [Releases](https://github.com/dunalduck0/plugin.video.cnvod/releases/latest)
3. Add-ons → **Install from zip file** → pick the zip
4. Open from **Video Add-ons → CN VOD → Search**
5. Recent searches show up under the Search row so you don't have to retype Chinese on a TV remote

For **HLS playback with custom Referer headers**, the **Input Stream Adaptive** addon must be enabled (bundled with Kodi 19+, just not enabled by default on some platforms).

## How it works (olevod)

Clean-room reverse-engineered from the live JS bundle `tv-pc-main.*.js`:

* Every API GET takes a `_vv=<sig>` query param. `sig` is computed from the unix-seconds timestamp by:
  1. Take each digit char, write its ASCII value in binary, slice bits 2,3,4,5+ into 4 column-strings.
  2. Parse each column as binary, format as left-padded 3-char hex.
  3. Interleave the 4 hex pieces into the md5 hex of the timestamp at fixed offsets.
* Endpoints:
  * `GET https://api.olelive.com/v1/pub/index/search/{q}/0/0/0/1` → search
  * `GET https://api.olelive.com/v1/pub/vod/detail/{id}/true` → metadata + episode list with m3u8 URLs
* Playback CDN requires `Referer: https://www.olevod.com/` — passed via `inputstream.adaptive.stream_headers`.

See [`resources/lib/sites/olevod.py`](resources/lib/sites/olevod.py) for the implementation.

## Project layout

```
addon.xml                       # Kodi manifest
default.py                      # router (search / episodes / play)
resources/
  lib/
    sites/
      base.py                   # SiteProvider abstract + dataclasses
      olevod.py                 # olevod extractor (clean-room)
      iyftv.py                  # iyf.tv extractor (stub, Phase 2)
tools/
  probe_olevod.py               # standalone CLI for testing without Kodi
```

## Develop / debug without Kodi

```powershell
# Search and inspect detail for video id 75514
$env:PYTHONIOENCODING="utf-8"
python tools\probe_olevod.py 75514
```

## Releases

A push of a `vX.Y.Z` tag triggers `.github/workflows/release.yml` which builds the zip and publishes a GitHub release. Locally:

```powershell
.\build.ps1     # produces dist/plugin.video.cnvod-<version>.zip
```

## License

MIT
