"""Abstract base class for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PostResult:
    """Result of a post operation."""

    success: bool
    post_id: str = ""
    url: str = ""
    error: str = ""


class PlatformAdapter(ABC):
    """Interface that every platform adapter must implement."""

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the platform using resolved credentials."""
        ...

    @abstractmethod
    async def post(self, content: str, media_url: str | None = None) -> PostResult:
        """Publish a post. Returns a PostResult with outcome details."""
        ...

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Check that stored credentials are valid. Returns True if OK."""
        ...
