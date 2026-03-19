"""Tests for prompt template assembly."""

from __future__ import annotations

from src.config import BotConfig
from src.content.prompts import (
    build_generation_prompt,
    build_system_prompt,
)


def _make_config(**overrides) -> BotConfig:
    base = {
        "persona": {"name": "TestBot"},
        "content": {
            "tone": ["sarcastic", "dry"],
            "topics": ["AI", "gaming"],
            "style": {"max_length": 280, "capitalization": "minimal", "punctuation": "minimal"},
            "lean": "test lean implied through humor",
            "guidelines": ["never be explicit", "keep it brief"],
        },
    }
    base.update(overrides)
    return BotConfig(**base)


def test_system_prompt_contains_tone() -> None:
    config = _make_config()
    prompt = build_system_prompt(config)
    assert "sarcastic" in prompt
    assert "dry" in prompt


def test_system_prompt_contains_persona_name() -> None:
    config = _make_config()
    prompt = build_system_prompt(config)
    assert "TestBot" in prompt


def test_system_prompt_no_persona_when_empty() -> None:
    config = _make_config(persona={"name": "", "handle": ""})
    prompt = build_system_prompt(config)
    assert "persona name is" not in prompt


def test_system_prompt_contains_guidelines() -> None:
    config = _make_config()
    prompt = build_system_prompt(config)
    assert "never be explicit" in prompt
    assert "keep it brief" in prompt


def test_generation_prompt_picks_topic() -> None:
    config = _make_config()
    prompt = build_generation_prompt(config)
    assert "AI" in prompt or "gaming" in prompt


def test_generation_prompt_includes_emoji_flag() -> None:
    config = _make_config()
    prompt = build_generation_prompt(config, include_emoji=True)
    assert "emoji" in prompt.lower()


def test_generation_prompt_includes_gif_flag() -> None:
    config = _make_config()
    prompt = build_generation_prompt(config, include_gif=True)
    assert "gif" in prompt.lower()


def test_generation_prompt_avoids_recent() -> None:
    config = _make_config()
    recent = ["old post about AI hype"]
    prompt = build_generation_prompt(config, recent_posts=recent)
    assert "old post about AI hype" in prompt
