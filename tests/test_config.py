"""Tests for config loading and validation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.config import BotConfig, load_config


@pytest.fixture
def minimal_config_data() -> dict:
    return {
        "persona": {"name": "TestBot", "handle": "@testbot"},
        "posting": {"min_interval_minutes": 60, "max_interval_minutes": 120},
        "content": {
            "tone": ["sarcastic"],
            "topics": ["AI", "gaming"],
            "style": {"max_length": 280},
            "lean": "test lean",
            "guidelines": ["be nice"],
        },
        "platform": "twitter",
        "platform_config": {
            "twitter": {
                "api_key_env": "TWITTER_API_KEY",
                "api_secret_env": "TWITTER_API_SECRET",
                "access_token_env": "TWITTER_ACCESS_TOKEN",
                "access_secret_env": "TWITTER_ACCESS_SECRET",
            }
        },
    }


@pytest.fixture
def config_file(minimal_config_data: dict, tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(minimal_config_data), encoding="utf-8")
    return path


def test_load_config_from_file(config_file: Path) -> None:
    config = load_config(config_file)
    assert config.persona.name == "TestBot"
    assert config.platform == "twitter"
    assert "sarcastic" in config.content.tone


def test_load_config_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path.yaml")


def test_defaults_applied() -> None:
    config = BotConfig()
    assert config.posting.min_interval_minutes == 90
    assert config.posting.max_interval_minutes == 300
    assert config.content.style.max_length == 280
    assert config.content.prompting.affinity_mode == "lean_charitable_people"
    assert config.content.prompting.recent_posts_window == 5
    assert config.engagement.replies.min_replies_per_post == 5
    assert config.logging.level == "INFO"


def test_invalid_interval_order() -> None:
    with pytest.raises(ValueError, match="max_interval_minutes"):
        BotConfig(posting={"min_interval_minutes": 200, "max_interval_minutes": 100})


def test_emoji_probability_bounds() -> None:
    with pytest.raises(ValueError):
        BotConfig(content={"style": {"emoji_probability": 1.5}})


def test_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="logging.level"):
        BotConfig(logging={"level": "VERBOSE"})


def test_invalid_affinity_mode() -> None:
    with pytest.raises(ValueError, match="content.prompting.affinity_mode"):
        BotConfig(content={"prompting": {"affinity_mode": "unknown"}})


def test_invalid_reply_cap_order() -> None:
    with pytest.raises(ValueError, match="engagement.replies.max_replies_per_post"):
        BotConfig(engagement={"replies": {"min_replies_per_post": 8, "max_replies_per_post": 5}})


def test_invalid_reply_poll_interval_order() -> None:
    with pytest.raises(ValueError, match="engagement.replies.poll_interval_seconds_max"):
        BotConfig(
            engagement={
                "replies": {
                    "poll_interval_seconds_min": 90,
                    "poll_interval_seconds_max": 30,
                }
            }
        )


def test_invalid_reply_emoji_probability() -> None:
    with pytest.raises(ValueError):
        BotConfig(engagement={"replies": {"positive_emoji_probability": 1.2}})


def test_get_platform_credentials(minimal_config_data: dict) -> None:
    config = BotConfig(**minimal_config_data)
    env_vars = {
        "TWITTER_API_KEY": "key123",
        "TWITTER_API_SECRET": "secret123",
        "TWITTER_ACCESS_TOKEN": "token123",
        "TWITTER_ACCESS_SECRET": "tsecret123",
    }
    for k, v in env_vars.items():
        os.environ[k] = v
    try:
        creds = config.get_platform_credentials()
        assert creds["api_key_env"] == "key123"
        assert creds["access_token_env"] == "token123"
    finally:
        for k in env_vars:
            os.environ.pop(k, None)


def test_missing_credential_env_var(minimal_config_data: dict) -> None:
    config = BotConfig(**minimal_config_data)
    # Ensure env vars are NOT set
    for var in ["TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"]:
        os.environ.pop(var, None)

    with pytest.raises(EnvironmentError, match="Required env var"):
        config.get_platform_credentials()


def test_old_content_config_still_loads_without_prompting_block(minimal_config_data: dict) -> None:
    config = BotConfig(**minimal_config_data)
    assert config.content.prompting.variation_modes
    assert config.content.prompting.affinity_mode == "lean_charitable_people"
