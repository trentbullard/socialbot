"""Trending context fetching — platform search and LM-based research."""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request

from loguru import logger

from src.config import BotConfig
from src.platforms.base import PlatformAdapter, TrendingPost


def _format_platform_context(posts: list[TrendingPost]) -> str:
    """Format platform search results into prompt context."""
    if not posts:
        return ""

    # Collect unique hashtags across all posts
    all_hashtags: list[str] = []
    seen_tags: set[str] = set()
    for p in posts:
        for tag in p.hashtags:
            lower = tag.lower()
            if lower not in seen_tags:
                seen_tags.add(lower)
                all_hashtags.append(tag)

    lines = ["Here is what people are currently talking about on this topic:"]
    for i, p in enumerate(posts[:8], 1):
        snippet = p.text[:200].replace("\n", " ")
        lines.append(f"  {i}. \"{snippet}\"")

    if all_hashtags:
        lines.append(f"\nTrending hashtags: {', '.join(f'#{t}' for t in all_hashtags[:15])}")

    return "\n".join(lines)


async def fetch_platform_trending(
    config: BotConfig,
    adapter: PlatformAdapter,
    topic: str,
) -> str:
    """Fetch trending posts from the platform adapter for a given topic."""
    max_results = config.content.trending.max_results
    logger.debug("Searching platform for trending posts on: {}", topic)

    posts = await adapter.search_recent(topic, max_results=max_results)
    context = _format_platform_context(posts)

    if context:
        logger.info("Got trending context from platform ({} posts, {} chars)", len(posts), len(context))
    else:
        logger.debug("No platform trending context found for: {}", topic)

    return context


def fetch_lm_trending(config: BotConfig, topic: str) -> str:
    """Ask the LM what's currently trending for a topic (two-step generation)."""
    research_prompt = (
        f"You are a social media trend researcher. "
        f"List 5-8 specific things people are currently talking about, debating, or memeing "
        f"about on social media related to: {topic}\n\n"
        f"Include specific hashtags, viral moments, controversies, or memes where applicable. "
        f"Be specific and current — reference actual events, people, or takes that are trending.\n\n"
        f"Respond with a concise bullet list only. No introduction or conclusion."
    )

    backend = config.generator_backend

    if backend == "vscode-lm":
        return _lm_research_via_vscode(config, research_prompt)
    elif backend == "codex":
        return _lm_research_via_codex(config, research_prompt)
    else:
        logger.warning("Unknown backend '{}' for LM trending research", backend)
        return ""


def _lm_research_via_vscode(config: BotConfig, prompt: str) -> str:
    """Call VS Code LM proxy for trending research."""
    host = config.vscode_lm.host
    port = config.vscode_lm.port
    url = f"http://{host}:{port}/generate"
    timeout = config.content.trending.timeout_seconds

    payload = json.dumps({"prompt": prompt, "timeout": timeout}).encode("utf-8")

    logger.debug("Sending trending research to LM proxy (timeout={}s)", timeout)

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        content = body.get("content", "").strip()
        if content:
            logger.info("LM trending research returned {} chars", len(content))
            return f"Here is what's currently trending on social media about this topic:\n{content}"
        return ""

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("LM trending research failed (timeout={}s): {}", timeout, exc)
        return ""


def _lm_research_via_codex(config: BotConfig, prompt: str) -> str:
    """Call Codex CLI for trending research."""
    import shutil
    import subprocess

    cli_path = config.codex.cli_path
    if not cli_path:
        for name in ("codex", "codex.exe", "codex-cli", "codex-cli.exe"):
            found = shutil.which(name)
            if found:
                cli_path = found
                break
    if not cli_path:
        logger.warning("Codex CLI not found — skipping LM trending research")
        return ""

    timeout = config.content.trending.timeout_seconds
    try:
        result = subprocess.run(
            [cli_path, "--full-auto", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        content = result.stdout.strip()
        if content and result.returncode == 0:
            logger.info("Codex trending research returned {} chars", len(content))
            return f"Here is what's currently trending on social media about this topic:\n{content}"
        return ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Codex trending research failed: {}", exc)
        return ""


async def fetch_trending_context(
    config: BotConfig,
    topic: str,
    adapter: PlatformAdapter | None = None,
) -> str:
    """Fetch trending context using the configured source(s).

    Returns a formatted string to inject into the generation prompt,
    or empty string if trending is disabled or nothing was found.
    """
    if not config.content.trending.enabled:
        return ""

    source = config.content.trending.source
    context_parts: list[str] = []

    # Platform search (requires an authenticated adapter)
    if source in ("platform", "both") and adapter is not None:
        platform_ctx = await fetch_platform_trending(config, adapter, topic)
        if platform_ctx:
            context_parts.append(platform_ctx)

    # LM-based research (works without platform auth — great for dry-run)
    if source in ("lm", "both"):
        lm_ctx = fetch_lm_trending(config, topic)
        if lm_ctx:
            context_parts.append(lm_ctx)

    # If "both" returned data from both, prefer the richer one (or join them)
    if not context_parts:
        logger.debug("No trending context found for topic: {}", topic)
        return ""

    combined = "\n\n".join(context_parts)
    logger.debug("Total trending context: {} chars", len(combined))
    return combined
