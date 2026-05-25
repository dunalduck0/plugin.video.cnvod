"""Test olevod VIP login end-to-end using credentials from .env.

Usage:
    python tools/test_vip_login.py
    python tools/test_vip_login.py "search query"
"""

from __future__ import annotations
import base64
import os
import subprocess
import sys
import re

# Load .env from repo root
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env = os.path.join(_root, ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.join(_root, "resources", "lib"))

from sites.olevod import OleVod, _do_login, _fetch_captcha, _save_token

USERNAME = os.environ.get("OLEVOD_USERNAME", "")
PASSWORD = os.environ.get("OLEVOD_PASSWORD", "")
QUERY = sys.argv[1] if len(sys.argv) > 1 else "碟中谍"
PROFILE_DIR = os.path.join(_root, ".dev_profile")
CAPTCHA_IMG = os.path.join(_root, "captcha.png")

if not USERNAME or USERNAME == "your_email_or_username":
    print("ERROR: Set OLEVOD_USERNAME and OLEVOD_PASSWORD in .env")
    sys.exit(1)

print(f"Logging in as: {USERNAME}")

# Fetch captcha, show path, ask user to type it
captcha_id, pic_b64 = _fetch_captcha()
with open(CAPTCHA_IMG, "wb") as f:
    f.write(base64.b64decode(pic_b64))
print(f"Captcha image: {CAPTCHA_IMG}")
subprocess.Popen(["start", CAPTCHA_IMG], shell=True)
captcha_text = input("Type the captcha characters: ").strip()

token = _do_login(USERNAME, PASSWORD, captcha_text, captcha_id)
print(f"Token: {token[:50]}...")
_save_token(PROFILE_DIR, USERNAME, token)
print(f"Token cached.")

o = OleVod()
o._token = token

print(f"\nSearching (authenticated): {QUERY}")
results = o.search(QUERY)
print(f"Results: {len(results)}")
for r in results[:3]:
    print(f"  [{r.id}] {r.title} ({r.subtitle})")

# Resolve the VIP test video: /player/vod/6-75512-1.html -> id=75512
print("\nResolving VIP test video (id=75512, ep=1)...")
info = o.resolve("75512", 1)
print(f"Title: {info.title}")
print(f"URL:   {info.url}")

import urllib.request
req = urllib.request.Request(
    info.url,
    headers={"Referer": "https://www.olevod.com/", "User-Agent": "Mozilla/5.0"}
)
with urllib.request.urlopen(req, timeout=10) as resp:
    m3u8 = resp.read().decode()
print(f"\nMaster playlist:\n{m3u8[:800]}")
resolutions = re.findall(r"RESOLUTION=(\d+x\d+)", m3u8)
bandwidths = re.findall(r"BANDWIDTH=(\d+)", m3u8)
print("\nQuality variants:")
for res, bw in zip(resolutions, bandwidths):
    print(f"  {res}  ({int(bw)/1_000_000:.1f} Mbps)")
