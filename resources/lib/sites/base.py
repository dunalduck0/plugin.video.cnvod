"""Abstract site provider for the cnvod addon.

Each site implementation exposes two operations:

    search(query) -> list[VideoResult]
    resolve(video_id, episode_index=1) -> StreamInfo

Both run on the Kodi device, so the underlying HTTP calls happen from the
user's TV (important for IP-bound streams like iyf.tv).
"""

from dataclasses import dataclass, field


@dataclass
class VideoResult:
    site: str
    id: str
    title: str
    subtitle: str = ""            # e.g. "高清", "1080P", typeIdName
    thumbnail: str | None = None
    plot: str = ""
    year: str = ""
    is_series: bool = False
    episode_count: int = 1


@dataclass
class Episode:
    index: int
    title: str
    url: str


@dataclass
class StreamInfo:
    url: str
    headers: dict = field(default_factory=dict)
    title: str = ""
    thumbnail: str | None = None
    is_hls: bool = True


class SiteProvider:
    """Subclasses must implement search() and resolve()."""

    id: str = ""        # short site key e.g. "olevod"
    name: str = ""      # human-readable e.g. "OleVOD"

    def search(self, query: str) -> list[VideoResult]:
        raise NotImplementedError

    def list_episodes(self, video_id: str) -> list[Episode]:
        """Return episode list for a multi-part video (or single entry for movies)."""
        raise NotImplementedError

    def resolve(self, video_id: str, episode_index: int = 1) -> StreamInfo:
        raise NotImplementedError
