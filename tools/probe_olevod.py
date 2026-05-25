"""Standalone probe for olevod.com API. Reverse-engineered _vv signing.

JS source from https://www.olevod.com/js/tv-pc-main.1772799258000.js:

  function he(e){let t=[],r=e.split("");for(var i=0;i<r.length;i++){0!=i&&t.push(" ");
    let e=r[i].charCodeAt().toString(2); t.push(e)} return t.join("")}
  function fe(e){let t=e.toString(),r=[[],[],[],[]];
    for(var i=0;i<t.length;i++){let e=he(t[i]);
      r[0]+=e.slice(2,3), r[1]+=e.slice(3,4), r[2]+=e.slice(4,5), r[3]+=e.slice(5)}
    ... pad hex to 3 chars ...
    let n=D(t);  // D = md5
    return n.slice(0,3)+a[0]+n.slice(6,11)+a[1]+n.slice(14,19)+a[2]+n.slice(22,27)+a[3]+n.slice(30)}

  _vv = fe(Date.parse(new Date)/1e3)   // seconds-since-epoch
"""
import hashlib
import sys
import time
import urllib.parse
import urllib.request


def _vv(ts: int) -> str:
    t = str(ts)
    r = ["", "", "", ""]
    for ch in t:
        # he(): each digit char is converted to binary (no padding).
        # ASCII digits are 48..57 -> 6 bits: '110000'..'111001'.
        b = bin(ord(ch))[2:]
        r[0] += b[2:3]
        r[1] += b[3:4]
        r[2] += b[4:5]
        r[3] += b[5:]
    a = []
    for s in r:
        hx = format(int(s, 2), "x") if s else ""
        if len(hx) == 2:
            hx = "0" + hx
        elif len(hx) == 1:
            hx = "00" + hx
        elif len(hx) == 0:
            hx = "000"
        a.append(hx)
    n = hashlib.md5(t.encode()).hexdigest()
    return (
        n[0:3] + a[0] + n[6:11] + a[1] + n[14:19] + a[2] + n[22:27] + a[3] + n[30:]
    )


API = "https://api.olelive.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.olevod.com",
    "Referer": "https://www.olevod.com/",
    "Accept": "application/json, text/plain, */*",
}


def get(path: str, params: dict | None = None) -> str:
    params = dict(params or {})
    params["_vv"] = _vv(int(time.time()))
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


if __name__ == "__main__":
    vid = sys.argv[1] if len(sys.argv) > 1 else "75514"
    print(f"=== detail/{vid}/true ===")
    print(get(f"/v1/pub/vod/detail/{vid}/true")[:2000])
