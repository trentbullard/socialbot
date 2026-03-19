"""Abstract base class for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PostResult:
    """Result of a post operation."""

    success: bool
    post_id: str = ""
    url: str = ""
    error: str = ""


@dataclass
class TrendingPost:
    """A single trending/recent post returned by platform search."""

    text: str
    author: str = ""
    engagement: int = 0
    hashtags: list[str] = field(default_factory=list)


class PlatformAdapter(ABC):
    """Interface that every platform adapter must implement."""

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the platform using resolved credentials."""
        ...

    @abstractmethod
    async def post(self, content: str, media_path: str | None = None) -> PostResult:
        """Publish a post, optionally with a media attachment. Returns a PostResult."""
        ...

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Check that stored credentials are valid. Returns True if OK."""
        ...

    async def search_recent(self, query: str, max_results: int = 10) -> list[TrendingPost]:
        """Search for recent popular posts matching a query. Optional — returns [] by default."""
        return []
