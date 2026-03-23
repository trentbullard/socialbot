"""Prompt template assembly from configuration parameters."""

from __future__ import annotations

import random

from src.config import BotConfig


def pick_variation_mode(config: BotConfig) -> str:
    """Pick a rhetorical mode for the next post."""
    modes = config.content.prompting.variation_modes
    if not modes:
        return "observation"
    return random.choice(modes)


def pick_engagement_goal(config: BotConfig) -> str | None:
    """Pick an engagement focus for the next post."""
    goals = config.content.prompting.engagement_goals
    if not goals:
        return None
    return random.choice(goals)


def _format_bullets(items: list[str], *, fallback: str) -> str:
    if not items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in items)


def summarize_recent_patterns(config: BotConfig, recent_posts: list[str] | None = None) -> str:
    """Return recent-post context to discourage repetitive generations."""
    if not recent_posts:
        return ""

    window = max(1, min(config.content.prompting.recent_posts_window, 5))
    posts = [post.strip() for post in recent_posts[-window:] if post.strip()]
    if not posts:
        return ""

    lines = [f"Your last {len(posts)} posts:"]
    lines.extend(f"  {index}. {post}" for index, post in enumerate(posts, start=1))
    lines.append(
        "Avoid posting in a way that feels repetitive when compared to these posts. "
        "Do not reuse the same setup, cadence, framing, or punchline."
    )
    return "\n".join(lines)


def build_system_prompt(
    config: BotConfig,
    *,
    variation_mode: str | None = None,
    engagement_goal: str | None = None,
) -> str:
    """Build the system-level prompt that defines the persona and rules."""
    tone_str = ", ".join(config.content.tone)
    guidelines_str = _format_bullets(config.content.guidelines, fallback="none")
    prompting = config.content.prompting

    persona_line = ""
    if config.persona.name:
        persona_line = f"Your persona name is {config.persona.name}. "

    chosen_mode = variation_mode or (prompting.variation_modes[0] if prompting.variation_modes else "observation")
    chosen_goal = engagement_goal or (prompting.engagement_goals[0] if prompting.engagement_goals else "")

    strategy_lines = [f"- Primary variation mode for this post: {chosen_mode}"]
    if chosen_goal:
        strategy_lines.append(f"- Secondary engagement focus for this post: {chosen_goal}")
    strategy_block = "\n".join(strategy_lines)

    affinity_block = "- Affinity guidance disabled"
    if prompting.affinity_mode == "lean_charitable_people":
        affinity_lines = [
            "- Infer alignment from the worldview above, not from hard-coded ideology labels",
            "- Apply this only to people, creators, or public figures",
            *[f"- {instruction}" for instruction in prompting.affinity_instructions],
            "- Criticism is still allowed for clear factual conflict, hypocrisy, or obvious failure",
        ]
        affinity_block = "\n".join(affinity_lines)

    return (
        f"You are a social media persona. {persona_line}"
        f"Your tone is: {tone_str}. "
        f"Your worldview: {config.content.lean}. "
        "This worldview must be implied through humor and framing, never stated directly.\n\n"
        f"Style rules:\n"
        f"- Maximum {config.content.style.max_length} characters\n"
        f"- Capitalization: {config.content.style.capitalization}\n"
        f"- Punctuation: {config.content.style.punctuation}\n"
        f"- Write a single standalone post, not a thread\n"
        f"- Brief and punchy, one idea only\n"
        f"- No explicit questions or engagement CTAs unless the user config later asks for them\n\n"
        f"Prompt strategy:\n{strategy_block}\n\n"
        f"Engagement goals:\n{_format_bullets(prompting.engagement_goals, fallback='favor concrete specifics')}\n\n"
        f"Engagement anti-patterns:\n{_format_bullets(prompting.engagement_anti_patterns, fallback='avoid filler')}\n\n"
        f"Discouraged post patterns:\n{_format_bullets(prompting.discouraged_patterns, fallback='avoid stale patterns')}\n\n"
        f"Affinity guidance:\n{affinity_block}\n\n"
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
    topic: str | None = None,
) -> str:
    """Build the user-level prompt for a single post generation."""
    chosen_topic = topic or pick_topic(config)
    recent_posts_context = summarize_recent_patterns(config, recent_posts)

    parts = [
        f"Write a single social media post about: {chosen_topic}",
        "Use the selected variation mode from the system prompt instead of falling back to a default format.",
        "Lead with one concrete observation, one sharp contrast, or one precise implication.",
        "Prefer specific names, events, or details over broad abstractions.",
    ]

    if trending_context:
        parts.append(
            f"\n{trending_context}\n\n"
            "Use the above trending context for inspiration. Reference a specific event, person, "
            "or angle when it sharpens the post. Do not just summarize the news dump.\n"
            "The bullets are listed most-recent-first. Prefer a recent story unless an older item "
            "is clearly more important."
        )

    if include_emoji:
        parts.append("Include one or two relevant humorous emojis.")

    if include_gif:
        parts.append(
            "Suggest a well-known reaction gif or meme image that would pair with this post "
            "(describe it in brackets, e.g. [gif: confused Nick Young])."
        )

    if recent_posts_context:
        parts.append(f"\n{recent_posts_context}")

    if config.content.prompting.discouraged_patterns:
        discouraged = "\n".join(
            f"  - {pattern}" for pattern in config.content.prompting.discouraged_patterns
        )
        parts.append(f"\nAlso avoid these stale fallback patterns:\n{discouraged}")

    parts.append(
        "\nMake it feel like a human who noticed something true before everyone else, "
        "not a generic content machine. Avoid vague hashtags unless they are central to the joke."
    )
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
