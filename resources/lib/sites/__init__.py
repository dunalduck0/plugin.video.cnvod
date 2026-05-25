"""Site provider registry."""

from __future__ import annotations

from .base import Episode, SiteProvider, StreamInfo, VideoResult
from .olevod import OleVod
from .iyftv import IyfTv
from .huavod import HuaVod

PROVIDERS: dict[str, SiteProvider] = {
    OleVod.id: OleVod(),
    IyfTv.id: IyfTv(),
    HuaVod.id: HuaVod(),
}

__all__ = [
    "PROVIDERS",
    "SiteProvider",
    "VideoResult",
    "Episode",
    "StreamInfo",
]
