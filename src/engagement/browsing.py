"""Passive browsing and liking engine for organic between-post activity."""

from __future__ import annotations

import asyncio
import random

from loguru import logger

from src.config import BotConfig
from src.platforms.base import PlatformAdapter


class BrowsingEngine:
    """Periodically searches topic-adjacent content and likes posts organically."""

    def __init__(
        self,
        config: BotConfig,
        adapter: PlatformAdapter,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self._rng = rng or random.Random()
        self._liked_ids: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.config.engagement.browsing.enabled

    async def run_loop(self, shutdown_event: asyncio.Event) -> None:
        if not self.enabled:
            logger.debug("Browse engine disabled")
            return

        logger.info("Browse engine enabled")
        while True:
            if shutdown_event.is_set():
                logger.info("Browse engine stopping on shutdown")
                return

            try:
                await self.browse_once()
            except Exception:
                logger.exception("Browse engine session failed")

            settings = self.config.engagement.browsing
            interval = self._rng.uniform(
                settings.interval_minutes_min * 60,
                settings.interval_minutes_max * 60,
            )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                logger.info("Browse engine stopping during sleep")
                return
            except asyncio.TimeoutError:
                continue

    async def browse_once(self) -> None:
        """Search a random topic and like a small batch of relevant posts."""
        settings = self.config.engagement.browsing
        topics = self.config.content.topics
        if not topics:
            return

        topic = self._rng.choice(topics)
        logger.debug("Browse session: searching topic '{}'", topic)

        results = await self.adapter.search_recent(topic, max_results=20)
        if not results:
            logger.debug("Browse session: no results for '{}'", topic)
            return

        shuffled = list(results)
        self._rng.shuffle(shuffled)

        likes_target = self._rng.randint(
            settings.likes_per_pass_min,
            settings.likes_per_pass_max,
        )
        liked = 0

        for post in shuffled:
            if liked >= likes_target:
                break
            if not post.post_id or post.post_id in self._liked_ids:
                continue
            if self._rng.random() >= settings.like_probability:
                continue

            success = await self.adapter.like_post(post.post_id)
            if success:
                self._liked_ids.add(post.post_id)
                liked += 1

        if liked:
            logger.info("Browse session: liked {} post(s) for topic '{}'", liked, topic)
        else:
            logger.debug("Browse session: no posts liked for topic '{}'", topic)
