"""Abstract base class for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


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
    post_id: str = ""
    author: str = ""
    engagement: int = 0
    hashtags: list[str] = field(default_factory=list)


@dataclass
class RemotePost:
    """A post or reply fetched from the platform (used for startup history sync)."""

    post_id: str
    content: str
    post_type: Literal["post", "reply"]
    created_at: datetime


@dataclass
class ReplyCandidate:
    """A direct reply candidate discovered for a bot-authored post."""

    reply_id: str
    parent_post_id: str
    author_id: str
    author_handle: str
    text: str
    created_at: datetime
    has_media: bool = False


class PlatformAdapter(ABC):
    """Interface that every platform adapter must implement."""

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the platform using resolved credentials."""
        ...

    @abstractmethod
    async def post(
        self,
        content: str,
        media_path: str | None = None,
        in_reply_to_post_id: str | None = None,
    ) -> PostResult:
        """Publish a post, optionally with a media attachment. Returns a PostResult."""
        ...

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Check that stored credentials are valid. Returns True if OK."""
        ...

    async def search_recent(self, query: str, max_results: int = 10) -> list[TrendingPost]:
        """Search for recent popular posts matching a query. Optional — returns [] by default."""
        return []

    async def like_post(self, post_id: str) -> bool:
        """Like a post by ID. Optional — returns False by default."""
        return False

    async def list_direct_replies(
        self,
        post_id: str,
        since_id: str | None = None,
    ) -> list[ReplyCandidate]:
        """List direct replies to a bot-authored post. Optional — returns [] by default."""
        return []

    async def get_recent_posts(self, limit: int = 100) -> list[RemotePost]:
        """Fetch the account's most recent posts/replies for startup history sync. Optional — returns [] by default."""
        return []

    def get_authenticated_user_id(self) -> str:
        """Return the authenticated platform user id when known."""
        return ""
