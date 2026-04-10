"""Cross-session post and reply history for prompt context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger


@dataclass
class PostRecord:
    """A single post or reply authored by the bot."""

    timestamp: datetime
    content: str
    post_type: Literal["post", "reply"]
    post_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "post_type": self.post_type,
        }
        if self.post_id is not None:
            d["post_id"] = self.post_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PostRecord":
        ts = datetime.fromisoformat(str(data["timestamp"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        post_type = str(data.get("post_type", "post"))
        if post_type not in ("post", "reply"):
            post_type = "post"
        raw_id = data.get("post_id")
        post_id = str(raw_id) if raw_id else None
        return cls(
            timestamp=ts,
            content=str(data.get("content", "")),
            post_type=post_type,  # type: ignore[arg-type]
            post_id=post_id,
        )


class PostHistoryStore:
    """Persists the bot's own post and reply history across restarts."""

    def __init__(self, path: str | Path, max_entries: int = 200) -> None:
        self.path = Path(path)
        self.max_entries = max_entries
        self._records: list[PostRecord] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = [PostRecord.from_dict(r) for r in raw.get("history", [])]
            logger.info("Loaded {} post history entries from {}", len(self._records), self.path)
        except Exception:
            logger.exception("Failed to load post history from {}", self.path)
            self._records = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = {"history": [r.to_dict() for r in self._records]}
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def add(
        self,
        content: str,
        post_type: Literal["post", "reply"] = "post",
        post_id: str | None = None,
    ) -> None:
        record = PostRecord(
            timestamp=datetime.now(timezone.utc),
            content=content,
            post_type=post_type,
            post_id=post_id,
        )
        self._records.insert(0, record)
        if len(self._records) > self.max_entries:
            self._records = self._records[: self.max_entries]
        self.save()

    def sync_from_remote(self, remote_records: list[PostRecord]) -> int:
        """Merge remote records into local history, deduplicating by post_id then content.

        Records are merged newest-first, trimmed to max_entries, and saved atomically.
        Returns the number of newly added records.
        """
        known_ids: set[str] = {r.post_id for r in self._records if r.post_id is not None}
        known_contents: set[str] = {r.content for r in self._records}

        added = 0
        for record in remote_records:
            if record.post_id is not None and record.post_id in known_ids:
                continue
            if record.content in known_contents:
                continue
            self._records.append(record)
            known_contents.add(record.content)
            if record.post_id is not None:
                known_ids.add(record.post_id)
            added += 1

        if added:
            self._records.sort(key=lambda r: r.timestamp, reverse=True)
            if len(self._records) > self.max_entries:
                self._records = self._records[: self.max_entries]
            self.save()

        return added

    def get_recent(self, n: int) -> list[PostRecord]:
        """Return the n most recent records, newest first."""
        return list(self._records[:n])

    def get_recent_for_prompt(self, n: int) -> list[str]:
        """Return recent entries as labeled strings suitable for prompt injection."""
        return [f"[{r.post_type}] {r.content}" for r in self.get_recent(n)]
