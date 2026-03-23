"""Tests for reply engagement and reply-aware platform integration."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import BotConfig
from src.engagement.replies import ReplyEngagementManager
from src.platforms.base import PostResult, ReplyCandidate


def _make_config(tmp_path, **overrides) -> BotConfig:
    base = {
        "content": {
            "tone": ["sarcastic"],
            "topics": ["AI"],
            "style": {"max_length": 280},
            "lean": "test lean",
            "guidelines": [],
        },
        "generator_backend": "codex",
        "codex": {"cli_path": "/usr/bin/codex", "timeout_seconds": 5},
        "engagement": {
            "state_path": str(tmp_path / "engagement-state.json"),
            "replies": {
                "enabled": True,
                "min_replies_per_post": 2,
                "max_replies_per_post": 2,
                "window_minutes": 120,
                "poll_interval_seconds_min": 1,
                "poll_interval_seconds_max": 1,
                "reply_delay_seconds_min": 0,
                "reply_delay_seconds_max": 0,
                "allow_neutral_as_positive": True,
                "max_replies_per_user_per_post": 1,
                "positive_emoji_probability": 0.0,
                "negative_emoji_probability": 0.0,
            },
        },
    }
    base.update(overrides)
    return BotConfig(**base)


def _candidate(
    reply_id: str,
    *,
    parent_post_id: str = "root",
    author_id: str = "user-1",
    author_handle: str = "user1",
    text: str = "great point lol",
    minutes_after: int = 1,
) -> ReplyCandidate:
    return ReplyCandidate(
        reply_id=reply_id,
        parent_post_id=parent_post_id,
        author_id=author_id,
        author_handle=author_handle,
        text=text,
        created_at=datetime.now(timezone.utc) + timedelta(minutes=minutes_after),
    )


async def _no_sleep(_: float) -> None:
    return None


def test_reply_manager_processes_oldest_first_and_stops_at_target(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[
        _candidate("30", minutes_after=3, author_id="user-3"),
        _candidate("10", minutes_after=1, author_id="user-1"),
        _candidate("20", minutes_after=2, author_id="user-2"),
    ])
    adapter.post = AsyncMock(side_effect=lambda *args, **kwargs: PostResult(success=True, post_id=f"reply-{kwargs['in_reply_to_post_id']}"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(config, adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def scenario() -> None:
        await manager.register_post("root", created_at=datetime.now(timezone.utc))
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there"):
            await manager.poll_once()

    asyncio.run(scenario())

    assert adapter.post.await_count == 2
    replied_to_ids = [call.kwargs["in_reply_to_post_id"] for call in adapter.post.await_args_list]
    assert replied_to_ids == ["10", "20"]


def test_reply_manager_limits_one_reply_per_author(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[
        _candidate("10", author_id="same-user"),
        _candidate("11", author_id="same-user", minutes_after=2, text="still true though"),
    ])
    adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(config, adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def scenario() -> None:
        await manager.register_post("root", created_at=datetime.now(timezone.utc))
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there"):
            await manager.poll_once()

    asyncio.run(scenario())

    assert adapter.post.await_count == 1
    state = manager.store.get_post("root")
    assert state is not None
    assert state.replied_count == 1
    assert state.processed_reply_ids == {"10", "11"}


def test_reply_manager_skips_expired_post_windows(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[_candidate("10")])
    adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(config, adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def scenario() -> None:
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=121)
        await manager.register_post("root", created_at=expired_at)
        await manager.poll_once()

    asyncio.run(scenario())

    adapter.list_direct_replies.assert_not_awaited()
    assert manager.store.get_post("root") is None


def test_neutral_comments_route_to_positive_generation(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[_candidate("10", text="interesting point there")])
    adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(config, adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def scenario() -> None:
        await manager.register_post("root", created_at=datetime.now(timezone.utc))
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there") as mock_generate:
            await manager.poll_once()
            assert mock_generate.call_args.kwargs["sentiment"] == "positive"

    asyncio.run(scenario())


def test_reply_manager_dry_run_never_posts(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[_candidate("10")])
    adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(
        config,
        adapter,
        dry_run=True,
        rng=random.Random(0),
        sleep_func=_no_sleep,
    )

    async def scenario() -> None:
        await manager.register_post("root", created_at=datetime.now(timezone.utc))
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there"):
            await manager.poll_once()

    asyncio.run(scenario())

    adapter.post.assert_not_awaited()
    state = manager.store.get_post("root")
    assert state is not None
    assert "10" in state.processed_reply_ids


def test_reply_manager_persists_processed_state_across_restarts(tmp_path) -> None:
    config = _make_config(tmp_path)
    adapter = MagicMock()
    adapter.list_direct_replies = AsyncMock(return_value=[_candidate("10")])
    adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10"))
    adapter.get_authenticated_user_id.return_value = "bot-user"

    manager = ReplyEngagementManager(config, adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def first_run() -> None:
        await manager.register_post("root", created_at=datetime.now(timezone.utc))
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there"):
            await manager.poll_once()

    asyncio.run(first_run())

    second_adapter = MagicMock()
    second_adapter.list_direct_replies = AsyncMock(return_value=[_candidate("10")])
    second_adapter.post = AsyncMock(return_value=PostResult(success=True, post_id="reply-10-again"))
    second_adapter.get_authenticated_user_id.return_value = "bot-user"

    restarted_manager = ReplyEngagementManager(config, second_adapter, rng=random.Random(0), sleep_func=_no_sleep)

    async def second_run() -> None:
        with patch("src.engagement.replies.generate_reply", return_value="fair enough there"):
            await restarted_manager.poll_once()

    asyncio.run(second_run())

    second_adapter.post.assert_not_awaited()
    restored = restarted_manager.store.get_post("root")
    assert restored is not None
    assert restored.replied_count == 1
    assert "10" in restored.processed_reply_ids


def test_twitter_adapter_filters_direct_replies() -> None:
    pytest.importorskip("tweepy")
    from src.platforms.twitter import TwitterAdapter

    adapter = TwitterAdapter({})
    adapter._client = MagicMock()
    now = datetime.now(timezone.utc)

    adapter._client.search_recent_tweets.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(id="1", text="root", author_id="bot", created_at=now, referenced_tweets=[]),
            SimpleNamespace(
                id="2",
                text="first",
                author_id="user-1",
                created_at=now,
                referenced_tweets=[SimpleNamespace(type="replied_to", id="1")],
            ),
            SimpleNamespace(
                id="3",
                text="nested",
                author_id="user-2",
                created_at=now,
                referenced_tweets=[SimpleNamespace(type="replied_to", id="2")],
            ),
        ],
        includes={"users": [
            SimpleNamespace(id="user-1", username="alice"),
            SimpleNamespace(id="user-2", username="bob"),
        ]},
    )

    replies = asyncio.run(adapter.list_direct_replies("1"))

    assert [reply.reply_id for reply in replies] == ["2"]
    assert replies[0].author_handle == "alice"
    assert adapter._client.search_recent_tweets.call_args.kwargs["user_auth"] is True


def test_twitter_adapter_search_recent_uses_user_auth() -> None:
    pytest.importorskip("tweepy")
    from src.platforms.twitter import TwitterAdapter

    adapter = TwitterAdapter({})
    adapter._client = MagicMock()
    adapter._client.search_recent_tweets.return_value = SimpleNamespace(data=[])

    results = asyncio.run(adapter.search_recent("ai", max_results=10))

    assert results == []
    assert adapter._client.search_recent_tweets.call_args.kwargs["user_auth"] is True


def test_twitter_adapter_posts_replies_with_parent_id() -> None:
    pytest.importorskip("tweepy")
    from src.platforms.twitter import TwitterAdapter

    adapter = TwitterAdapter({})
    adapter._client = MagicMock()
    adapter._client.create_tweet.return_value = SimpleNamespace(data={"id": "999"})

    result = asyncio.run(adapter.post("fair enough there", in_reply_to_post_id="123"))

    assert result.success is True
    assert adapter._client.create_tweet.call_args.kwargs["in_reply_to_tweet_id"] == "123"
