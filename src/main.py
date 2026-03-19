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
from src.content.generator import generate_post
from src.content.giphy import download_gif, extract_gif_tag, search_gif
from src.content.prompts import pick_topic
from src.content.trends import fetch_trending_context
from src.platforms.base import PlatformAdapter
from src.platforms.twitter import TwitterAdapter
from src.scheduler import run_scheduler

# Registry of available platform adapters
PLATFORM_ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "twitter": TwitterAdapter,
}

# Rolling window of recent posts to avoid repetition
_recent_posts: list[str] = []
MAX_RECENT = 20


def _setup_logging(level: str) -> None:
    logger.remove()  # remove default handler
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def _build_adapter(config: BotConfig) -> PlatformAdapter:
    adapter_cls = PLATFORM_ADAPTERS.get(config.platform)
    if adapter_cls is None:
        logger.error("Unknown platform '{}'. Available: {}", config.platform, ", ".join(PLATFORM_ADAPTERS))
        raise ValueError(
            f"Unknown platform '{config.platform}'. "
            f"Available: {', '.join(PLATFORM_ADAPTERS)}"
        )
    logger.debug("Resolved platform adapter: {} -> {}", config.platform, adapter_cls.__name__)
    credentials = config.get_platform_credentials()
    return adapter_cls(credentials)


async def _post_cycle(config: BotConfig, adapter: PlatformAdapter) -> None:
    """Single generate-and-post cycle (live mode)."""
    logger.info("Starting post cycle")

    # Fetch trending context if enabled
    topic = pick_topic(config)
    trending_context = await fetch_trending_context(config, topic, adapter=adapter)
    if trending_context:
        logger.info("Injecting trending context ({} chars) for topic: {}", len(trending_context), topic)

    content = generate_post(config, recent_posts=_recent_posts, trending_context=trending_context)
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

    logger.info("-" * 60)
    logger.info("Generating sample post...")

    # Fetch trending context if enabled (LM-based works without auth)
    topic = pick_topic(config)
    trending_context = asyncio.run(fetch_trending_context(config, topic))
    if trending_context:
        logger.info("Trending context ({} chars) for topic: {}", len(trending_context), topic)
        logger.debug("Trending context:\n{}", trending_context)

    content = generate_post(config, recent_posts=_recent_posts, trending_context=trending_context)
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


async def _run(config: BotConfig, max_posts: int | None) -> None:
    """Live run: authenticate and start scheduler loop."""
    adapter = _build_adapter(config)

    logger.info("Authenticating with platform: {}", config.platform)
    await adapter.authenticate()
    if not await adapter.validate_credentials():
        logger.error("Credential validation failed — exiting")
        sys.exit(1)
    logger.info("Authenticated successfully with platform: {}", config.platform)

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
        await _post_cycle(config, adapter)

    logger.info("Starting scheduler loop (max_posts={}) — Ctrl+C to stop gracefully", max_posts or "unlimited")
    await run_scheduler(config, callback, max_posts=max_posts, shutdown_event=shutdown_event)
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
    args = parser.parse_args()

    config = load_config(args.config)
    _setup_logging(config.logging.level)

    logger.info("Loaded config from {}", args.config)

    if args.dry_run:
        _dry_run(config)
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
