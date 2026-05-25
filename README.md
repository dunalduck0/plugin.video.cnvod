# Kodi CN VOD Addon

Search and stream Chinese on-demand video sites (**olevod.com**, **iyf.tv**) directly inside Kodi — no PC, no DevTools, no `.strm` file shuffling.

## Status

| Site | Search | Play |
| --- | --- | --- |
| olevod.com | ✅ | ✅ (movies + multi-episode series) |
| iyf.tv | ⛔ Phase 2 | ⛔ Phase 2 |

iyf.tv signing is reverse-engineered separately and will be wired in once captured.

## Why an addon (instead of `.strm` files)?

* No PC needed — you can search and play from your TV remote
* Signed URLs expire (~24h); the addon mints a fresh one every play
* iyf.tv streams are IP-bound — the addon makes the API call from the TV so the IP matches
* Works for multi-episode TV series, not just single movies

## Install

1. Settings → System → Add-ons → enable **Unknown sources**
2. Build the zip:
   ```powershell
   cd plugin.video.cnvod
   .\build.ps1     # produces plugin.video.cnvod-0.1.0.zip in dist\
   ```
3. In Kodi: Add-ons → Install from zip file → pick the zip
4. Open from **Video Add-ons → CN VOD → Search**

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

## License

MIT
