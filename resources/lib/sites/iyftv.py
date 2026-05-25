"""iyf.tv extractor — STUB.

Phase 2 of the implementation. Requires the user to share a DevTools capture
of a real `m10.iyf.tv/v3/video/play?...` request (URL + JSON response) so
we can reverse-engineer the signing algorithm.

Until then this provider is registered but raises NotImplementedError if
called, so the addon stays usable for olevod alone.
"""

from __future__ import annotations

from .base import Episode, SiteProvider, StreamInfo, VideoResult


class IyfTv(SiteProvider):
    id = "iyftv"
    name = "iyf.tv"

    def search(self, query: str) -> list[VideoResult]:
        # TODO Phase 2: reverse-engineer m10.iyf.tv/v3/search-result
        return []

    def list_episodes(self, video_id: str) -> list[Episode]:
        raise NotImplementedError("iyf.tv extractor not yet implemented")

    def resolve(self, video_id: str, episode_index: int = 1) -> StreamInfo:
        raise NotImplementedError("iyf.tv extractor not yet implemented")
