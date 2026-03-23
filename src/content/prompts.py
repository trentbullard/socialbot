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


def build_reply_system_prompt(config: BotConfig) -> str:
    """Build the system prompt for terse comment replies."""
    tone_str = ", ".join(config.content.tone)
    guidelines_str = "\n".join(f"- {g}" for g in config.content.guidelines)

    return (
        "You are writing a reply from the same social media persona.\n"
        f"Tone: {tone_str}.\n"
        f"Worldview: {config.content.lean}. Keep it implied.\n\n"
        "Reply rules:\n"
        "- Sound like an extremely terse, quick human reaction\n"
        "- Usually 1 to 6 words, and never rambling\n"
        "- Lowercase or minimal capitalization only\n"
        "- Minimal punctuation\n"
        "- No hashtags, no links, no @mentions, no questions\n"
        "- One brief acknowledgement, recognition, or dismissal only\n"
        "- Do not explain, justify, debate, or invite more discussion\n\n"
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
            "Use the above trending context for inspiration — reference a specific event, "
            "take, or hashtag where it makes sense. Don't just summarize it; "
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


def build_reply_generation_prompt(
    comment_text: str,
    *,
    sentiment: str,
    emoji: str | None,
) -> str:
    """Build the user prompt for a short reply to a single comment."""
    sentiment_instructions = {
        "positive": "Sound amused, approving, or lightly agreeing.",
        "negative": "Sound dismissive, lightly mocking, or unimpressed.",
    }
    instruction = sentiment_instructions.get(sentiment, "Keep the reaction brief.")

    emoji_instruction = (
        f"Include exactly this emoji once at the end: {emoji}"
        if emoji
        else "Do not use any emoji."
    )

    return (
        "Reply to this comment:\n"
        f"{comment_text}\n\n"
        f"{instruction}\n"
        f"{emoji_instruction}\n"
        "Respond with ONLY the reply text."
    )


def should_include_emoji(config: BotConfig) -> bool:
    return random.random() < config.content.style.emoji_probability


def should_include_gif(config: BotConfig) -> bool:
    return random.random() < config.content.style.gif_probability


def pick_topic(config: BotConfig) -> str:
    """Pick a random topic from the configured pool."""
    return random.choice(config.content.topics) if config.content.topics else "current events"
