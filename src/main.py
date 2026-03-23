"""Main entry point and orchestrator for the social media bot."""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import sys
from datetime import datetime, timezone

from loguru import logger

from src.config import BotConfig, load_config
from src.content.generator import generate_post, generate_reply, preview_reply_prompts
from src.content.giphy import download_gif, extract_gif_tag, search_gif
from src.content.prompts import pick_topic
from src.content.trends import fetch_trending_context
from src.engagement.replies import ReplyEngagementManager, classify_reply_sentiment
from src.platforms.base import PlatformAdapter
from src.scheduler import run_scheduler

AVAILABLE_PLATFORMS = ("twitter",)

# Rolling window of recent posts to avoid repetition
_recent_posts: list[str] = []
MAX_RECENT = 20
DEFAULT_REPLY_DRY_RUN_COMMENTS = [
    "lol this is actually true",
    "based take",
    "nah this is dumb",
    "you are completely wrong here",
    "interesting point honestly",
]


def _setup_logging(level: str) -> None:
    logger.remove()  # remove default handler
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def _build_adapter(config: BotConfig) -> PlatformAdapter:
    adapter_cls: type[PlatformAdapter] | None = None
    if config.platform == "twitter":
        from src.platforms.twitter import TwitterAdapter

        adapter_cls = TwitterAdapter

    if adapter_cls is None:
        logger.error("Unknown platform '{}'. Available: {}", config.platform, ", ".join(AVAILABLE_PLATFORMS))
        raise ValueError(
            f"Unknown platform '{config.platform}'. "
            f"Available: {', '.join(AVAILABLE_PLATFORMS)}"
        )
    logger.debug("Resolved platform adapter: {} -> {}", config.platform, adapter_cls.__name__)
    credentials = config.get_platform_credentials()
    return adapter_cls(credentials)


async def _post_cycle(
    config: BotConfig,
    adapter: PlatformAdapter,
    reply_manager: ReplyEngagementManager | None = None,
) -> None:
    """Single generate-and-post cycle (live mode)."""
    logger.info("Starting post cycle")

    # Fetch trending context if enabled
    topic = pick_topic(config)
    trending_context = await fetch_trending_context(config, topic, adapter=adapter)
    if trending_context:
        logger.info("Injecting trending context ({} chars) for topic: {}", len(trending_context), topic)

    content = generate_post(
        config,
        recent_posts=_recent_posts,
        trending_context=trending_context,
        topic=topic,
    )
    if content is None:
        logger.warning("Skipping post slot — generation failed")
        return

    # Extract GIF tag, search Giphy, download
    content, gif_query = extract_gif_tag(content)
    media_path: str | None = None
    if gif_query:
        gif_url = search_gif(gif_query, config)
        if gif_url:
            media_path = download_gif(gif_url, timeout=config.giphy.timeout_seconds)

    # Small human-like delay before posting
    jitter = random.uniform(
        config.posting.jitter_seconds_min,
        config.posting.jitter_seconds_max,
    )
    logger.debug("Pre-post jitter: {:.1f}s", jitter)
    await asyncio.sleep(jitter)

    try:
        result = await adapter.post(content, media_path=media_path)
        if result.success:
            logger.info("Posted successfully | id={} | url={}", result.post_id, result.url)
        else:
            logger.error("Post failed: {}", result.error)
            return
    finally:
        # Clean up temp GIF file
        if media_path:
            try:
                os.remove(media_path)
            except OSError:
                pass

    _recent_posts.append(content)
    if len(_recent_posts) > MAX_RECENT:
        _recent_posts.pop(0)

    if result.post_id and reply_manager is not None:
        await reply_manager.register_post(
            result.post_id,
            created_at=datetime.now(timezone.utc),
        )


def _dry_run(config: BotConfig) -> None:
    """Dry-run mode: bypass all platform auth, generate one post, log with metadata."""
    logger.info("=" * 60)
    logger.info("DRY RUN — no platform authentication, no posting")
    logger.info("=" * 60)

    # Log config summary
    logger.info("Persona  : name={!r} handle={!r}", config.persona.name, config.persona.handle)
    logger.info("Platform : {}", config.platform)
    logger.info("Tone     : {}", ", ".join(config.content.tone))
    logger.info("Topics   : {}", ", ".join(config.content.topics[:5]) + (" ..." if len(config.content.topics) > 5 else ""))
    logger.info("Style    : max_length={} caps={} punct={} emoji_p={} gif_p={}",
                config.content.style.max_length,
                config.content.style.capitalization,
                config.content.style.punctuation,
                config.content.style.emoji_probability,
                config.content.style.gif_probability)
    logger.info("Cadence  : {}-{} min interval, {}-{} posts/day",
                config.posting.min_interval_minutes,
                config.posting.max_interval_minutes,
                config.posting.posts_per_day_min,
                config.posting.posts_per_day_max)
    if config.engagement.replies.enabled:
        logger.info("Replies  : enabled {}-{} per post over {} minutes",
                    config.engagement.replies.min_replies_per_post,
                    config.engagement.replies.max_replies_per_post,
                    config.engagement.replies.window_minutes)

    logger.info("-" * 60)
    logger.info("Generating sample post...")

    # Fetch trending context if enabled (LM-based works without auth)
    topic = pick_topic(config)
    trending_context = asyncio.run(fetch_trending_context(config, topic))
    if trending_context:
        logger.info("Trending context ({} chars) for topic: {}", len(trending_context), topic)
        logger.debug("Trending context:\n{}", trending_context)

    content = generate_post(
        config,
        recent_posts=_recent_posts,
        trending_context=trending_context,
        topic=topic,
    )
    now = datetime.now(timezone.utc)

    if content is None:
        logger.error("Content generation failed — check Codex CLI configuration")
        return

    # Extract and resolve GIF tag
    content, gif_query = extract_gif_tag(content)
    gif_info = ""
    if gif_query:
        gif_url = search_gif(gif_query, config)
        if gif_url:
            gif_info = f"  GIF     : query={gif_query!r} → {gif_url}"
        else:
            gif_info = f"  GIF     : query={gif_query!r} → no Giphy result (set {config.giphy.api_key_env}?)"

    logger.info("-" * 60)
    logger.info("SAMPLE POST")
    logger.info("  Timestamp : {} UTC", now.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  Platform  : {}", config.platform)
    logger.info("  Persona   : {} ({})", config.persona.name or "<not set>", config.persona.handle or "<not set>")
    logger.info("  Length    : {} / {} chars", len(content), config.content.style.max_length)
    if gif_info:
        logger.info(gif_info)
    logger.info("  Content   :")
    logger.info("")
    logger.info("    {}", content)
    logger.info("")
    logger.info("-" * 60)
    logger.info("Dry run complete.")


def _choose_preview_emoji(config: BotConfig, sentiment: str) -> str | None:
    settings = config.engagement.replies
    if sentiment == "positive":
        if random.random() <= settings.positive_emoji_probability:
            return random.choice(settings.positive_emojis)
        return None
    if sentiment == "negative":
        if random.random() <= settings.negative_emoji_probability:
            return random.choice(settings.negative_emojis)
    return None


def _dry_run_replies(config: BotConfig, comments: list[str] | None = None) -> None:
    """Dry-run reply generation locally without platform auth or posting."""
    logger.info("=" * 60)
    logger.info("REPLY DRY RUN — no platform authentication, no posting")
    logger.info("=" * 60)

    sample_comments = comments or DEFAULT_REPLY_DRY_RUN_COMMENTS
    logger.info("Reply samples: {}", len(sample_comments))
    logger.info("Reply backend: {}", config.generator_backend)
    logger.info("Positive emojis: {}", ", ".join(config.engagement.replies.positive_emojis))
    logger.info("Negative emojis: {}", ", ".join(config.engagement.replies.negative_emojis))

    for index, comment in enumerate(sample_comments, start=1):
        raw_sentiment = classify_reply_sentiment(comment)
        effective_sentiment = raw_sentiment
        if raw_sentiment == "neutral" and config.engagement.replies.allow_neutral_as_positive:
            effective_sentiment = "positive"

        logger.info("-" * 60)
        logger.info("SAMPLE REPLY {}", index)
        logger.info("  Comment           : {}", comment)
        logger.info("  Raw sentiment     : {}", raw_sentiment)
        logger.info("  Effective bucket  : {}", effective_sentiment)

        if effective_sentiment == "skip":
            logger.info("  Action            : skipped")
            continue

        emoji = _choose_preview_emoji(config, effective_sentiment)
        system_prompt, user_prompt = preview_reply_prompts(
            config,
            comment_text=comment,
            sentiment=effective_sentiment,
            emoji=emoji,
        )
        reply = generate_reply(
            config,
            comment_text=comment,
            sentiment=effective_sentiment,
            emoji=emoji,
        )

        logger.info("  Emoji             : {}", emoji or "<none>")
        logger.info("  Reply             : {}", reply or "<invalid / generation failed>")
        logger.info("  Prompt context    :")
        logger.info("")
        logger.info("    [system]")
        for line in system_prompt.splitlines():
            logger.info("    {}", line)
        logger.info("")
        logger.info("    [user]")
        for line in user_prompt.splitlines():
            logger.info("    {}", line)
        logger.info("")

    logger.info("-" * 60)
    logger.info("Reply dry run complete.")


async def _post_now(config: BotConfig) -> None:
    """Authenticate and immediately post once, then exit."""
    adapter = _build_adapter(config)

    logger.info("Authenticating with platform: {}", config.platform)
    await adapter.authenticate()
    if not await adapter.validate_credentials():
        logger.error("Credential validation failed — exiting")
        sys.exit(1)
    logger.info("Authenticated — posting immediately")

    reply_manager = ReplyEngagementManager(config, adapter)
    await _post_cycle(config, adapter, reply_manager=reply_manager)
    logger.info("Immediate post complete.")


async def _run(config: BotConfig, max_posts: int | None) -> None:
    """Live run: authenticate and start scheduler loop."""
    adapter = _build_adapter(config)

    logger.info("Authenticating with platform: {}", config.platform)
    await adapter.authenticate()
    if not await adapter.validate_credentials():
        logger.error("Credential validation failed — exiting")
        sys.exit(1)
    logger.info("Authenticated successfully with platform: {}", config.platform)

    reply_manager = ReplyEngagementManager(config, adapter)
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Received shutdown signal (Ctrl+C) — finishing current cycle...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler; fall back below
            pass

    async def callback() -> None:
        await _post_cycle(config, adapter, reply_manager=reply_manager)

    reply_task: asyncio.Task[None] | None = None
    if reply_manager.enabled:
        reply_task = asyncio.create_task(reply_manager.run_loop(shutdown_event))

    logger.info("Starting scheduler loop (max_posts={}) — Ctrl+C to stop gracefully", max_posts or "unlimited")
    await run_scheduler(config, callback, max_posts=max_posts, shutdown_event=shutdown_event)
    shutdown_event.set()
    if reply_task is not None:
        await reply_task
    logger.info("Bot stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Social Media Bot")
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate a sample post and log it — no auth, no posting",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Stop after N posts (useful for testing)",
    )
    parser.add_argument(
        "--post-now",
        action="store_true",
        help="Authenticate and post once immediately, then exit",
    )
    parser.add_argument(
        "--dry-run-replies",
        action="store_true",
        help="Generate sample reply prompts and replies locally — no auth, no posting",
    )
    parser.add_argument(
        "--reply-comment",
        action="append",
        default=[],
        help="Sample comment for --dry-run-replies. Repeat to supply multiple comments.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    _setup_logging(config.logging.level)

    logger.info("Loaded config from {}", args.config)

    if args.dry_run_replies:
        _dry_run_replies(config, args.reply_comment or None)
    elif args.dry_run:
        _dry_run(config)
    elif args.post_now:
        logger.info("Post-now mode — will post once and exit")
        try:
            asyncio.run(_post_now(config))
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down.")
    else:
        logger.info("Platform: {} | Max posts: {}", config.platform, args.max_posts or "unlimited")
        try:
            asyncio.run(_run(config, args.max_posts))
        except KeyboardInterrupt:
            # Windows fallback — add_signal_handler isn't supported, so
            # Ctrl+C raises KeyboardInterrupt directly
            logger.info("Interrupted — shutting down.")


if __name__ == "__main__":
    main()
