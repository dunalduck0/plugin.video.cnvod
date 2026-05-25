"""Recent-searches history persisted in the addon profile dir.

Keeps the last N queries (default 20) in a plain newline-delimited file so
the user can pick a prior search from the root menu instead of re-typing
Chinese on a TV remote.
"""

from __future__ import annotations

import os

MAX_ENTRIES = 20


def _path(profile_dir: str) -> str:
    return os.path.join(profile_dir, "history.txt")


def load(profile_dir: str) -> list[str]:
    p = _path(profile_dir)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def add(profile_dir: str, query: str) -> None:
    query = (query or "").strip()
    if not query:
        return
    items = [q for q in load(profile_dir) if q != query]
    items.insert(0, query)
    items = items[:MAX_ENTRIES]
    os.makedirs(profile_dir, exist_ok=True)
    try:
        with open(_path(profile_dir), "w", encoding="utf-8") as f:
            f.write("\n".join(items))
    except OSError:
        pass


def clear(profile_dir: str) -> None:
    p = _path(profile_dir)
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass
