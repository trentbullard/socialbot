"""Randomized posting scheduler with jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from src.config import BotConfig


def _next_interval(config: BotConfig) -> float:
    """Calculate the next sleep interval in seconds with random jitter."""
    base = random.uniform(
        config.posting.min_interval_minutes * 60,
        config.posting.max_interval_minutes * 60,
    )
    jitter = random.uniform(
        config.posting.jitter_seconds_min,
        config.posting.jitter_seconds_max,
    )
    return base + jitter


async def run_scheduler(
    config: BotConfig,
    post_callback: Callable[[], Coroutine[Any, Any, None]],
    max_posts: int | None = None,
) -> None:
    """Run the posting loop on a randomized schedule.

    Args:
        config: Bot configuration.
        post_callback: Async callable invoked each cycle to generate & post.
        max_posts: If set, stop after this many posts (useful for testing).
    """
    posts_made = 0

    while True:
        interval = _next_interval(config)
        next_mins = interval / 60
        logger.info("Next post in %.1f minutes", next_mins)

        await asyncio.sleep(interval)

        try:
            await post_callback()
            posts_made += 1
            logger.info("Posts completed today: %d", posts_made)
        except Exception:
            logger.exception("Error during post cycle")

        if max_posts is not None and posts_made >= max_posts:
            logger.info("Reached max_posts limit (%d), stopping scheduler", max_posts)
            break
