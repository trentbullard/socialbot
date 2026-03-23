"""Tests for the scheduler module."""

from __future__ import annotations

import asyncio

import pytest

from src.config import BotConfig
from src.scheduler import _next_interval, run_scheduler


def test_next_interval_range() -> None:
    config = BotConfig(
        posting={
            "min_interval_minutes": 1,
            "max_interval_minutes": 2,
            "jitter_seconds_min": 0,
            "jitter_seconds_max": 10,
        }
    )
    for _ in range(50):
        interval = _next_interval(config)
        assert 60 <= interval <= 130  # 1min..2min base + 0..10s jitter

def test_scheduler_max_posts() -> None:
    config = BotConfig(
        posting={
            "min_interval_minutes": 0,
            "max_interval_minutes": 0,
            "jitter_seconds_min": 0,
            "jitter_seconds_max": 0,
        }
    )
    call_count = 0

    async def callback() -> None:
        nonlocal call_count
        call_count += 1

    asyncio.run(run_scheduler(config, callback, max_posts=3))
    assert call_count == 3
