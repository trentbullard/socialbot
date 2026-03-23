"""Tests for CLI-local dry-run helpers."""

from __future__ import annotations

from unittest.mock import patch

from src.config import BotConfig
from src.main import _dry_run_replies


def _make_config() -> BotConfig:
    return BotConfig(
        content={
            "tone": ["sarcastic"],
            "topics": ["AI"],
            "style": {"max_length": 280},
            "lean": "test",
            "guidelines": [],
        },
        generator_backend="codex",
        codex={"cli_path": "/usr/bin/codex", "timeout_seconds": 5},
        engagement={
            "replies": {
                "enabled": True,
                "positive_emoji_probability": 0.0,
                "negative_emoji_probability": 0.0,
            }
        },
    )


def test_dry_run_replies_uses_local_generation_only() -> None:
    config = _make_config()

    with patch("src.main.preview_reply_prompts", return_value=("system", "user")) as mock_preview:
        with patch("src.main.generate_reply", return_value="fair enough there") as mock_generate:
            _dry_run_replies(config, ["lol this is actually true"])

    mock_preview.assert_called_once()
    mock_generate.assert_called_once()
