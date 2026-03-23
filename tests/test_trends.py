"""Tests for trending context features."""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import BotConfig
from src.content.prompts import build_generation_prompt
from src.content.trends import (
    _format_platform_context,
    fetch_lm_trending,
    fetch_trending_context,
)
from src.platforms.base import TrendingPost


def _make_config(**overrides) -> BotConfig:
    base = {
        "persona": {"name": "TestBot"},
        "content": {
            "tone": ["sarcastic"],
            "topics": ["AI", "gaming"],
            "style": {"max_length": 280},
            "lean": "test lean",
            "guidelines": ["be nice"],
            "trending": {"enabled": True, "source": "lm", "max_results": 5},
        },
        "generator_backend": "vscode-lm",
        "vscode_lm": {"host": "127.0.0.1", "port": 0, "timeout_seconds": 5},
    }
    base.update(overrides)
    return BotConfig(**base)


# ---------------------------------------------------------------------------
# Tests for _format_platform_context
# ---------------------------------------------------------------------------

def test_format_platform_context_empty() -> None:
    assert _format_platform_context([]) == ""


def test_format_platform_context_with_posts() -> None:
    posts = [
        TrendingPost(text="AI is wild right now", hashtags=["AI", "tech"], engagement=100),
        TrendingPost(text="Gamers rise up", hashtags=["gaming"], engagement=50),
    ]
    result = _format_platform_context(posts)
    assert "currently talking about" in result
    assert "AI is wild right now" in result
    assert "#AI" in result
    assert "#gaming" in result


def test_format_platform_context_deduplicates_hashtags() -> None:
    posts = [
        TrendingPost(text="Post 1", hashtags=["AI", "tech"], engagement=10),
        TrendingPost(text="Post 2", hashtags=["ai", "new"], engagement=5),
    ]
    result = _format_platform_context(posts)
    # "AI" and "ai" should deduplicate (case-insensitive)
    assert result.count("#AI") + result.count("#ai") == 1


# ---------------------------------------------------------------------------
# Tests for trending config validation
# ---------------------------------------------------------------------------

def test_trending_config_defaults() -> None:
    config = BotConfig()
    assert config.content.trending.enabled is False
    assert config.content.trending.source == "lm"
    assert config.content.trending.max_results == 10
    assert config.content.trending.timeout_seconds == 300


def test_trending_config_invalid_source() -> None:
    with pytest.raises(ValueError, match="trending.source"):
        _make_config(content={
            "tone": ["sarcastic"],
            "topics": ["AI"],
            "style": {"max_length": 280},
            "lean": "test",
            "guidelines": [],
            "trending": {"enabled": True, "source": "magic"},
        })


# ---------------------------------------------------------------------------
# Tests for trending context in prompts
# ---------------------------------------------------------------------------

def test_generation_prompt_includes_trending_context() -> None:
    config = _make_config()
    prompt = build_generation_prompt(
        config,
        trending_context="Currently trending: AI taking everyone's jobs",
    )
    assert "AI taking everyone's jobs" in prompt
    assert "Reference a specific event, person, or angle" in prompt


def test_generation_prompt_no_trending_when_empty() -> None:
    config = _make_config()
    prompt = build_generation_prompt(config, trending_context="")
    assert "sharp take" not in prompt


# ---------------------------------------------------------------------------
# Tests for fetch_trending_context
# ---------------------------------------------------------------------------
def test_fetch_trending_disabled() -> None:
    config = _make_config(content={
        "tone": ["sarcastic"],
        "topics": ["AI"],
        "style": {"max_length": 280},
        "lean": "test",
        "guidelines": [],
        "trending": {"enabled": False, "source": "lm"},
    })
    result = asyncio.run(fetch_trending_context(config, "AI"))
    assert result == ""


def test_fetch_trending_platform_source() -> None:
    config = _make_config(content={
        "tone": ["sarcastic"],
        "topics": ["AI"],
        "style": {"max_length": 280},
        "lean": "test",
        "guidelines": [],
        "trending": {"enabled": True, "source": "platform"},
    })
    mock_adapter = AsyncMock()
    mock_adapter.search_recent.return_value = [
        TrendingPost(text="AI is everywhere", hashtags=["AI"], engagement=100),
    ]
    result = asyncio.run(fetch_trending_context(config, "AI", adapter=mock_adapter))
    assert "AI is everywhere" in result
    mock_adapter.search_recent.assert_called_once()


def test_fetch_trending_lm_via_http() -> None:
    """Test LM trending research using a real local HTTP server."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps({"content": "- GPT-5 rumors\n- AI art backlash\n- Coding agents hype"})
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass  # suppress output

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    try:
        config = _make_config(
            vscode_lm={"host": "127.0.0.1", "port": port, "timeout_seconds": 5},
        )
        result = fetch_lm_trending(config, "AI developments")
        assert "GPT-5 rumors" in result
        assert "trending" in result.lower()
    finally:
        server.shutdown()


def test_fetch_trending_lm_via_codex_uses_exec() -> None:
    config = _make_config(
        generator_backend="codex",
        codex={"cli_path": "/usr/bin/codex", "timeout_seconds": 5},
        content={
            "tone": ["sarcastic"],
            "topics": ["AI", "gaming"],
            "style": {"max_length": 280},
            "lean": "test lean",
            "guidelines": ["be nice"],
            "trending": {"enabled": True, "source": "lm", "max_results": 5, "timeout_seconds": 7},
        },
    )
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "- AI chips\n- model launches"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = fetch_lm_trending(config, "AI developments")

    assert "AI chips" in result
    assert mock_run.call_args.args[0] == [
        "/usr/bin/codex",
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "-",
    ]
