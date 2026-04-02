"""Tests for the scheduler module."""

from __future__ import annotations

import asyncio

import pytest
from loguru import logger

from src.config import BotConfig
from src.scheduler import _format_interval, _next_interval, run_scheduler


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


def test_format_interval_human_readable() -> None:
    assert _format_interval(59.6) == "1 minute"
    assert _format_interval(3661) == "1 hour 1 minute 1 second"


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


@pytest.mark.parametrize(
    ("enabled", "expected_message"),
    [
        (True, "Next post in 1 minute 5 seconds"),
        (False, None),
    ],
)
def test_scheduler_countdown_logging(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    expected_message: str | None,
) -> None:
    config = BotConfig(logging={"log_next_post_countdown": enabled})

    async def callback() -> None:
        return None

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("src.scheduler._next_interval", lambda _: 65.0)
    monkeypatch.setattr("src.scheduler.asyncio.sleep", no_sleep)

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message).strip()), format="{message}")
    try:
        asyncio.run(run_scheduler(config, callback, max_posts=1))
    finally:
        logger.remove(sink_id)

    joined = "\n".join(messages)
    if expected_message is None:
        assert "Next post in" not in joined
    else:
        assert expected_message in joined
