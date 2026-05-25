"""Site provider registry."""

from __future__ import annotations

from .base import Episode, SiteProvider, StreamInfo, VideoResult
from .olevod import OleVod
from .iyftv import IyfTv

PROVIDERS: dict[str, SiteProvider] = {
    OleVod.id: OleVod(),
    IyfTv.id: IyfTv(),
}

__all__ = [
    "PROVIDERS",
    "SiteProvider",
    "VideoResult",
    "Episode",
    "StreamInfo",
]
