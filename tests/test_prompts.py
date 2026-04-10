"""Tests for prompt template assembly."""

from __future__ import annotations

from src.config import BotConfig
from src.content.prompts import (
    build_generation_prompt,
    build_intent_classification_prompt,
    build_system_prompt,
    summarize_recent_patterns,
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
    prompt = build_system_prompt(config, variation_mode="contrast", engagement_goal="lead with a concrete observation")
    assert "sarcastic" in prompt
    assert "dry" in prompt


def test_system_prompt_contains_persona_name() -> None:
    config = _make_config()
    prompt = build_system_prompt(config, variation_mode="deadpan", engagement_goal="prefer specific nouns")
    assert "TestBot" in prompt


def test_system_prompt_no_persona_when_empty() -> None:
    config = _make_config(persona={"name": "", "handle": ""})
    prompt = build_system_prompt(config, variation_mode="observation")
    assert "persona name is" not in prompt


def test_system_prompt_contains_guidelines() -> None:
    config = _make_config()
    prompt = build_system_prompt(config, variation_mode="contrast")
    assert "never be explicit" in prompt
    assert "keep it brief" in prompt


def test_system_prompt_contains_prompting_strategy() -> None:
    config = _make_config()
    prompt = build_system_prompt(
        config,
        variation_mode="receipt",
        engagement_goal="make the reader feel they noticed something true",
    )
    assert "Primary variation mode for this post: receipt" in prompt
    assert "noticed something true" in prompt
    assert "Infer alignment from the worldview above" in prompt


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


def test_generation_prompt_uses_configured_recent_post_window() -> None:
    config = _make_config(content={
        "tone": ["sarcastic", "dry"],
        "topics": ["AI", "gaming"],
        "style": {"max_length": 280, "capitalization": "minimal", "punctuation": "minimal"},
        "lean": "test lean implied through humor",
        "guidelines": ["never be explicit", "keep it brief"],
        "prompting": {"recent_posts_window": 2},
    })
    recent = ["post one", "post two", "post three"]
    prompt = build_generation_prompt(config, recent_posts=recent, topic="AI")
    assert "post one" not in prompt
    assert "post two" in prompt
    assert "post three" in prompt


def test_recent_pattern_summary_returns_recent_post_context() -> None:
    config = _make_config(content={
        "tone": ["sarcastic", "dry"],
        "topics": ["AI", "gaming"],
        "style": {"max_length": 280, "capitalization": "minimal", "punctuation": "minimal"},
        "lean": "test lean implied through humor",
        "guidelines": ["never be explicit", "keep it brief"],
        "prompting": {"recent_posts_window": 5},
    })
    recent = [
        "ai is like netflix for bosses #future",
        "ai is like uber for powerpoint #innovation",
        "honestly the real issue is vibes, consultants, and powerpoint decks",
        "honestly the real issue is branding, vibes, and fake urgency",
    ]
    summary = summarize_recent_patterns(config, recent)
    assert "Your 4 most recent posts and replies" in summary
    assert "ai is like netflix for bosses #future" in summary
    assert "Vary your setup, framing" in summary


def test_generation_prompt_includes_recent_post_context_and_discouraged_patterns() -> None:
    config = _make_config(content={
        "tone": ["sarcastic", "dry"],
        "topics": ["AI", "gaming"],
        "style": {"max_length": 280, "capitalization": "minimal", "punctuation": "minimal"},
        "lean": "test lean implied through humor",
        "guidelines": ["never be explicit", "keep it brief"],
        "prompting": {
            "discouraged_patterns": ["forced pop-culture analogy"],
            "recent_posts_window": 5,
        },
    })
    recent = [
        "ai is like netflix for bosses #future",
        "ai is like uber for powerpoint #innovation",
    ]
    prompt = build_generation_prompt(config, recent_posts=recent, topic="AI")
    assert "Your 2 most recent posts and replies" in prompt
    assert "Vary your setup, framing" in prompt
    assert "forced pop-culture analogy" in prompt


def test_intent_classification_prompt_includes_original_post() -> None:
    prompt = build_intent_classification_prompt(
        "let's collab on something",
        original_post="hot take: AI is just autocomplete with a PR team",
    )
    assert "hot take: AI is just autocomplete with a PR team" in prompt
    assert "let's collab on something" in prompt
    assert "pitch" in prompt
    assert "normal" in prompt


def test_intent_classification_prompt_uses_placeholder_when_original_missing() -> None:
    prompt = build_intent_classification_prompt("interesting point")
    assert "(not available)" in prompt
    assert "interesting point" in prompt


def test_intent_classification_prompt_uses_placeholder_when_original_empty() -> None:
    prompt = build_intent_classification_prompt("interesting point", original_post="")
    assert "(not available)" in prompt


def test_intent_classification_prompt_uses_placeholder_when_original_whitespace() -> None:
    prompt = build_intent_classification_prompt("interesting point", original_post="   ")
    assert "(not available)" in prompt
