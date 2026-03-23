"""Persistent state storage for reply engagement."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class WatchedPostState:
    """Persisted reply-watching state for a single bot-authored post."""

    post_id: str
    created_at: datetime
    expires_at: datetime
    target_reply_count: int
    replied_count: int = 0
    last_seen_reply_id: str = ""
    processed_reply_ids: set[str] = field(default_factory=set)
    replied_author_counts: dict[str, int] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return self.replied_count >= self.target_reply_count

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current >= self.expires_at

    def to_dict(self) -> dict[str, object]:
        return {
            "post_id": self.post_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "target_reply_count": self.target_reply_count,
            "replied_count": self.replied_count,
            "last_seen_reply_id": self.last_seen_reply_id,
            "processed_reply_ids": sorted(self.processed_reply_ids),
            "replied_author_counts": self.replied_author_counts,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WatchedPostState":
        return cls(
            post_id=str(payload["post_id"]),
            created_at=_parse_datetime(str(payload["created_at"])),
            expires_at=_parse_datetime(str(payload["expires_at"])),
            target_reply_count=int(payload["target_reply_count"]),
            replied_count=int(payload.get("replied_count", 0)),
            last_seen_reply_id=str(payload.get("last_seen_reply_id", "") or ""),
            processed_reply_ids=set(payload.get("processed_reply_ids", [])),
            replied_author_counts={
                str(author_id): int(count)
                for author_id, count in dict(payload.get("replied_author_counts", {})).items()
            },
        )


class EngagementStateStore:
    """Loads and saves active reply-watching state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.active_posts: dict[str, WatchedPostState] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.active_posts = {}
            return

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        posts = raw.get("active_posts", [])
        self.active_posts = {
            post["post_id"]: WatchedPostState.from_dict(post)
            for post in posts
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = {
            "active_posts": [
                state.to_dict()
                for state in sorted(self.active_posts.values(), key=lambda item: item.created_at)
            ]
        }
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)

    def register_post(
        self,
        post_id: str,
        *,
        created_at: datetime,
        expires_at: datetime,
        target_reply_count: int,
    ) -> WatchedPostState:
        state = self.active_posts.get(post_id)
        if state is None:
            state = WatchedPostState(
                post_id=post_id,
                created_at=created_at,
                expires_at=expires_at,
                target_reply_count=target_reply_count,
            )
            self.active_posts[post_id] = state
            self.save()
        return state

    def get_post(self, post_id: str) -> WatchedPostState | None:
        return self.active_posts.get(post_id)

    def list_active_posts(self, now: datetime | None = None) -> list[WatchedPostState]:
        self.prune(now)
        return list(self.active_posts.values())

    def prune(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        removed = [
            post_id
            for post_id, state in self.active_posts.items()
            if state.is_complete() or state.is_expired(current)
        ]
        for post_id in removed:
            self.active_posts.pop(post_id, None)
        if removed:
            self.save()

    def remove_post(self, post_id: str) -> None:
        if self.active_posts.pop(post_id, None) is not None:
            self.save()

    def mark_processed(
        self,
        post_id: str,
        reply_id: str,
        *,
        newest_reply_id: str | None = None,
    ) -> None:
        state = self.active_posts.get(post_id)
        if state is None:
            return
        state.processed_reply_ids.add(reply_id)
        if newest_reply_id:
            state.last_seen_reply_id = newest_reply_id
        self.save()

    def mark_replied(
        self,
        post_id: str,
        reply_id: str,
        *,
        author_id: str,
        newest_reply_id: str | None = None,
    ) -> None:
        state = self.active_posts.get(post_id)
        if state is None:
            return
        state.processed_reply_ids.add(reply_id)
        state.replied_count += 1
        state.replied_author_counts[author_id] = state.replied_author_counts.get(author_id, 0) + 1
        if newest_reply_id:
            state.last_seen_reply_id = newest_reply_id
        self.save()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
