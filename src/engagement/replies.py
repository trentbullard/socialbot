"""Auto-reply engagement loop for early post comments."""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.config import BotConfig, EngagementRepliesConfig
from src.content.generator import generate_reply
from src.engagement.state import EngagementStateStore, WatchedPostState
from src.platforms.base import PlatformAdapter, ReplyCandidate

POSITIVE_PATTERNS = (
    "agree",
    "agreed",
    "based",
    "correct",
    "exactly",
    "facts",
    "fire",
    "funny",
    "good take",
    "great",
    "haha",
    "hilarious",
    "lol",
    "lmao",
    "love",
    "nice",
    "real",
    "right",
    "true",
    "valid",
    "yes",
)

NEGATIVE_PATTERNS = (
    "awful",
    "bad take",
    "clown",
    "cope",
    "cringe",
    "delusional",
    "dumb",
    "garbage",
    "hate this",
    "idiot",
    "loser",
    "moron",
    "nah",
    "pathetic",
    "stupid",
    "terrible",
    "trash",
    "wrong",
)

SEVERE_ABUSE_PATTERNS = (
    "go die",
    "kill yourself",
    "kys",
)

SPAM_PATTERNS = (
    "buy now",
    "check my profile",
    "dm me",
    "follow back",
    "promo code",
)


class ReplyEngagementManager:
    """Coordinates discovery, generation, and posting of auto-replies."""

    def __init__(
        self,
        config: BotConfig,
        adapter: PlatformAdapter,
        *,
        dry_run: bool = False,
        rng: random.Random | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self.settings: EngagementRepliesConfig = config.engagement.replies
        self.adapter = adapter
        self.dry_run = dry_run
        self.store = EngagementStateStore(config.engagement.state_path)
        self._rng = rng or random.Random()
        self._sleep = sleep_func or asyncio.sleep
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    async def register_post(self, post_id: str, *, created_at: datetime | None = None) -> None:
        if not self.enabled:
            return

        posted_at = _ensure_utc(created_at or datetime.now(timezone.utc))
        expires_at = posted_at + timedelta(minutes=self.settings.window_minutes)
        target = self._rng.randint(
            self.settings.min_replies_per_post,
            self.settings.max_replies_per_post,
        )

        async with self._lock:
            state = self.store.register_post(
                post_id,
                created_at=posted_at,
                expires_at=expires_at,
                target_reply_count=target,
            )

        logger.info(
            "Watching post {} for early replies (target={} expires={})",
            state.post_id,
            state.target_reply_count,
            state.expires_at.isoformat(),
        )

    async def run_loop(self, shutdown_event: asyncio.Event) -> None:
        if not self.enabled:
            logger.debug("Reply watcher disabled")
            return

        logger.info("Reply watcher enabled")
        while True:
            if shutdown_event.is_set():
                logger.info("Reply watcher stopping on shutdown request")
                return

            try:
                await self.poll_once()
            except Exception:
                logger.exception("Reply watcher poll failed")

            interval = self._rng.uniform(
                self.settings.poll_interval_seconds_min,
                self.settings.poll_interval_seconds_max,
            )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                logger.info("Reply watcher stopping during sleep")
                return
            except asyncio.TimeoutError:
                continue

    async def poll_once(self) -> None:
        if not self.enabled:
            return

        now = datetime.now(timezone.utc)
        async with self._lock:
            watched_posts = list(self.store.list_active_posts(now))

        for watched_post in watched_posts:
            if watched_post.is_complete():
                logger.info("Reply target reached for {}", watched_post.post_id)
                async with self._lock:
                    self.store.remove_post(watched_post.post_id)
                continue
            if watched_post.is_expired(now):
                logger.info("Reply window expired for {}", watched_post.post_id)
                async with self._lock:
                    self.store.remove_post(watched_post.post_id)
                continue
            await self._process_post(watched_post)

    async def _process_post(self, watched_post: WatchedPostState) -> None:
        candidates = await self.adapter.list_direct_replies(
            watched_post.post_id,
            since_id=watched_post.last_seen_reply_id or None,
        )
        if not candidates:
            return

        newest_reply_id = _max_reply_id(candidates)
        ordered_candidates = sorted(candidates, key=lambda item: (item.created_at, _reply_sort_key(item.reply_id)))

        for candidate in ordered_candidates:
            async with self._lock:
                current_state = self.store.get_post(watched_post.post_id)
            if current_state is None:
                return
            if current_state.is_complete():
                logger.info("Reply target reached for {}", current_state.post_id)
                async with self._lock:
                    self.store.remove_post(current_state.post_id)
                return
            if current_state.is_expired():
                logger.info("Reply window expired for {}", current_state.post_id)
                async with self._lock:
                    self.store.remove_post(current_state.post_id)
                return
            if candidate.reply_id in current_state.processed_reply_ids:
                continue

            skip_reason = self._skip_reason(current_state, candidate)
            if skip_reason:
                logger.debug(
                    "Skipping reply candidate {} on {}: {}",
                    candidate.reply_id,
                    current_state.post_id,
                    skip_reason,
                )
                async with self._lock:
                    self.store.mark_processed(
                        current_state.post_id,
                        candidate.reply_id,
                        newest_reply_id=newest_reply_id,
                    )
                continue

            sentiment = classify_reply_sentiment(candidate.text)
            if sentiment == "neutral" and self.settings.allow_neutral_as_positive:
                sentiment = "positive"
            if sentiment in {"neutral", "skip"}:
                logger.debug(
                    "Skipping reply candidate {} on {}: sentiment={}",
                    candidate.reply_id,
                    current_state.post_id,
                    sentiment,
                )
                async with self._lock:
                    self.store.mark_processed(
                        current_state.post_id,
                        candidate.reply_id,
                        newest_reply_id=newest_reply_id,
                    )
                continue

            emoji = self._choose_emoji(sentiment)
            reply_text = generate_reply(
                self.config,
                comment_text=candidate.text,
                sentiment=sentiment,
                emoji=emoji,
            )
            if reply_text is None:
                logger.warning(
                    "Generated invalid reply for {} on {}",
                    candidate.reply_id,
                    current_state.post_id,
                )
                async with self._lock:
                    self.store.mark_processed(
                        current_state.post_id,
                        candidate.reply_id,
                        newest_reply_id=newest_reply_id,
                    )
                continue

            if self.dry_run:
                logger.info(
                    "Dry run reply for {} on {} -> {}",
                    candidate.reply_id,
                    current_state.post_id,
                    reply_text,
                )
                async with self._lock:
                    self.store.mark_processed(
                        current_state.post_id,
                        candidate.reply_id,
                        newest_reply_id=newest_reply_id,
                    )
                continue

            delay = self._rng.uniform(
                self.settings.reply_delay_seconds_min,
                self.settings.reply_delay_seconds_max,
            )
            if delay > 0:
                await self._sleep(delay)

            result = await self.adapter.post(
                reply_text,
                in_reply_to_post_id=candidate.reply_id,
            )
            if result.success:
                logger.info(
                    "Auto-replied to {} on {} -> {}",
                    candidate.reply_id,
                    current_state.post_id,
                    result.post_id,
                )
                async with self._lock:
                    self.store.mark_replied(
                        current_state.post_id,
                        candidate.reply_id,
                        author_id=candidate.author_id,
                        newest_reply_id=newest_reply_id,
                    )
            else:
                logger.warning(
                    "Failed to auto-reply to {} on {}: {}",
                    candidate.reply_id,
                    current_state.post_id,
                    result.error,
                )
                async with self._lock:
                    self.store.mark_processed(
                        current_state.post_id,
                        candidate.reply_id,
                        newest_reply_id=newest_reply_id,
                    )

    def _skip_reason(self, watched_post: WatchedPostState, candidate: ReplyCandidate) -> str:
        text = candidate.text.strip()
        if not text:
            return "empty"
        if candidate.created_at > watched_post.expires_at:
            return "expired"
        if self.settings.skip_if_author_is_self and candidate.author_id == self.adapter.get_authenticated_user_id():
            return "self"
        if self.settings.skip_if_contains_links and _contains_link(text):
            return "link"
        if watched_post.replied_author_counts.get(candidate.author_id, 0) >= self.settings.max_replies_per_user_per_post:
            return "author-limit"
        if looks_like_spam(text):
            return "spam"
        return ""

    def _choose_emoji(self, sentiment: str) -> str | None:
        if sentiment == "positive":
            if self._rng.random() <= self.settings.positive_emoji_probability:
                return self._rng.choice(self.settings.positive_emojis)
            return None
        if self._rng.random() <= self.settings.negative_emoji_probability:
            return self._rng.choice(self.settings.negative_emojis)
        return None


def classify_reply_sentiment(text: str) -> str:
    """Bucket a reply as positive, negative, neutral, or skip."""
    lowered = text.lower()
    if any(pattern in lowered for pattern in SEVERE_ABUSE_PATTERNS):
        return "skip"

    positive_score = sum(1 for pattern in POSITIVE_PATTERNS if pattern in lowered)
    negative_score = sum(1 for pattern in NEGATIVE_PATTERNS if pattern in lowered)

    if positive_score == negative_score == 0:
        return "neutral"
    if negative_score > positive_score:
        return "negative"
    if positive_score > negative_score:
        return "positive"
    return "neutral"


def looks_like_spam(text: str) -> bool:
    lowered = text.lower()
    if any(pattern in lowered for pattern in SPAM_PATTERNS):
        return True
    if lowered.count("@") >= 3:
        return True
    if lowered.count("#") >= 4:
        return True
    return False


def _contains_link(text: str) -> bool:
    return bool(re.search(r"(https?://|www\.)", text, flags=re.IGNORECASE))


def _reply_sort_key(reply_id: str) -> int:
    try:
        return int(reply_id)
    except ValueError:
        return 0


def _max_reply_id(candidates: list[ReplyCandidate]) -> str:
    if not candidates:
        return ""
    return max(candidates, key=lambda item: _reply_sort_key(item.reply_id)).reply_id


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
