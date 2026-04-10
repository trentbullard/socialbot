"""Randomized posting scheduler with jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from src.config import BotConfig


def _get_scheduler_tz(config: BotConfig):
    tz_name = config.logging.timezone
    if tz_name == "local":
        return datetime.now().astimezone().tzinfo
    return ZoneInfo(tz_name)


def _adjust_for_active_hours(config: BotConfig, interval: float) -> float:
    """If the computed fire time falls outside active hours, advance to next window."""
    start = config.posting.active_hours_start
    end = config.posting.active_hours_end
    if start == 0 and end == 24:
        return interval

    tz = _get_scheduler_tz(config)
    now = datetime.now(tz)
    fire_dt = now + timedelta(seconds=interval)
    fire_hour = fire_dt.hour + fire_dt.minute / 60.0

    if start <= fire_hour < end:
        return interval  # Already within active window

    # Advance to the next window start
    candidate = fire_dt.replace(hour=start, minute=0, second=0, microsecond=0)
    if candidate <= fire_dt:
        candidate += timedelta(days=1)

    # Random offset so posts don't cluster at window open
    offset = random.uniform(0, 45 * 60)
    adjusted = (candidate - now).total_seconds() + offset
    logger.debug(
        "Active hours {}-{}: rescheduling fire from {:%H:%M} → {:%H:%M} (+{:.0f}s offset)",
        start,
        end,
        fire_dt,
        candidate + timedelta(seconds=offset),
        offset,
    )
    return adjusted


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
    return _adjust_for_active_hours(config, base + jitter)


def _format_interval(seconds: float) -> str:
    """Convert seconds into a concise human-readable duration."""
    remaining = max(0, int(round(seconds)))
    hours, remainder = divmod(remaining, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if minutes:
        parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
    if secs or not parts:
        parts.append(f"{secs} second" if secs == 1 else f"{secs} seconds")
    return " ".join(parts)


async def run_scheduler(
    config: BotConfig,
    post_callback: Callable[[], Coroutine[Any, Any, None]],
    max_posts: int | None = None,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run the posting loop on a randomized schedule.

    Args:
        config: Bot configuration.
        post_callback: Async callable invoked each cycle to generate & post.
        max_posts: If set, stop after this many posts (useful for testing).
        shutdown_event: If set, the scheduler will exit when this event is triggered.
    """
    posts_made = 0

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("Shutdown requested — exiting scheduler")
            break

        interval = _next_interval(config)
        if config.logging.log_next_post_countdown:
            logger.info("Next post in {}", _format_interval(interval))

        # Wait for the interval, but allow early exit on shutdown
        if shutdown_event:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                # Event was set — time to shut down
                logger.info("Shutdown requested during sleep — exiting scheduler")
                break
            except asyncio.TimeoutError:
                pass  # Normal: interval elapsed, proceed to post
        else:
            await asyncio.sleep(interval)

        try:
            await post_callback()
            posts_made += 1
            logger.info("Posts completed today: {}", posts_made)
        except Exception:
            logger.exception("Error during post cycle")

        if max_posts is not None and posts_made >= max_posts:
            logger.info("Reached max_posts limit (%d), stopping scheduler", max_posts)
            break
