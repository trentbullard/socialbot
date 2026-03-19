"""Prompt template assembly from configuration parameters."""

from __future__ import annotations

import random

from src.config import BotConfig


def build_system_prompt(config: BotConfig) -> str:
    """Build the system-level prompt that defines the persona and rules."""
    tone_str = ", ".join(config.content.tone)
    guidelines_str = "\n".join(f"- {g}" for g in config.content.guidelines)

    persona_line = ""
    if config.persona.name:
        persona_line = f"Your persona name is {config.persona.name}. "

    return (
        f"You are a social media persona. {persona_line}"
        f"Your tone is: {tone_str}. "
        f"Your worldview: {config.content.lean}. "
        f"This worldview must be implied through humor and framing — never stated directly.\n\n"
        f"Style rules:\n"
        f"- Maximum {config.content.style.max_length} characters\n"
        f"- Capitalization: {config.content.style.capitalization}\n"
        f"- Punctuation: {config.content.style.punctuation}\n"
        f"- Write a single standalone post, not a thread\n"
        f"- Brief and punchy — one idea only\n\n"
        f"Hard guidelines:\n{guidelines_str}"
    )


def build_generation_prompt(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    include_emoji: bool = False,
    include_gif: bool = False,
    trending_context: str = "",
) -> str:
    """Build the user-level prompt for a single post generation."""
    topic = random.choice(config.content.topics) if config.content.topics else "current events"

    parts = [f"Write a single social media post about: {topic}"]

    if trending_context:
        parts.append(
            f"\n{trending_context}\n\n"
            "Use the above trending context for inspiration — reference specific events, "
            "takes, or hashtags where it makes sense. Don't just summarize them; "
            "give your own sharp take.\n"
            "The bullets are listed most-recent-first. Prefer picking a story from the "
            "most recent items, but if an older bullet is clearly a bigger or more "
            "important story, prioritize that instead. Recency + importance."
        )

    if include_emoji:
        parts.append("Include one or two relevant humorous emojis.")

    if include_gif:
        parts.append(
            "Suggest a well-known reaction gif or meme image that would pair with this post "
            "(describe it in brackets, e.g. [gif: confused Nick Young])."
        )

    if recent_posts:
        # Provide last few posts so the model avoids repetition
        recent_str = "\n".join(f"  - {p}" for p in recent_posts[-5:])
        parts.append(f"\nAvoid repeating these recent posts:\n{recent_str}")

    parts.append("\nRespond with ONLY the post text. No quotes, no explanation.")

    return "\n".join(parts)


def should_include_emoji(config: BotConfig) -> bool:
    return random.random() < config.content.style.emoji_probability


def should_include_gif(config: BotConfig) -> bool:
    return random.random() < config.content.style.gif_probability


def pick_topic(config: BotConfig) -> str:
    """Pick a random topic from the configured pool."""
    return random.choice(config.content.topics) if config.content.topics else "current events"
