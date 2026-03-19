"""Trending context fetching — Brave Search RAG, platform search, and LM summarization."""

from __future__ import annotations

import gzip
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from loguru import logger

from src.config import BotConfig
from src.platforms.base import PlatformAdapter, TrendingPost


# ---------------------------------------------------------------------------
# Brave Search API — fetch real news/web results
# ---------------------------------------------------------------------------

def _fetch_brave_results(config: BotConfig, topic: str) -> list[dict]:
    """Call Brave Web Search API and return raw result dicts."""
    api_key = os.environ.get(config.brave_search.api_key_env, "")
    if not api_key:
        logger.warning(
            "Brave Search API key not set (env var: {}). Falling back to LM-only trending.",
            config.brave_search.api_key_env,
        )
        return []

    params = urllib.parse.urlencode({
        "q": topic,
        "count": config.brave_search.count,
        "freshness": config.brave_search.freshness,
        "text_decorations": "false",
    })
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    timeout = config.brave_search.timeout_seconds

    logger.debug("Brave Search: query={!r} freshness={} count={}", topic, config.brave_search.freshness, config.brave_search.count)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            body = json.loads(raw.decode("utf-8"))

        results = []
        for item in body.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "age": item.get("age", ""),
                "page_age": item.get("page_age", ""),
            })

        logger.info("Brave Search returned {} results for: {}", len(results), topic)
        return results

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Brave Search failed (timeout={}s): {}", timeout, exc)
        return []


def _format_brave_results_for_lm(results: list[dict], topic: str) -> str:
    """Format Brave Search results into a context block for LM summarization."""
    if not results:
        return ""

    lines = [f"Real search results about '{topic}' (most recent first):"]
    for i, r in enumerate(results, 1):
        age_str = f" ({r['age']})" if r["age"] else ""
        lines.append(f"  {i}. [{r['title']}]{age_str}")
        if r["description"]:
            desc = r["description"][:250].replace("\n", " ")
            lines.append(f"     {desc}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Platform-based trending context
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# LM-based summarization (grounded with Brave Search results when available)
# ---------------------------------------------------------------------------

def fetch_lm_trending(config: BotConfig, topic: str) -> str:
    """Fetch real search results via Brave, then ask the LM to summarize into bullet points."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %d, %Y %H:%M UTC")

    # Step 1: Fetch real search results from Brave
    brave_results = _fetch_brave_results(config, topic)
    brave_context = _format_brave_results_for_lm(brave_results, topic)

    if brave_context:
        # RAG path: ground the LM with real search results
        research_prompt = (
            f"You are a social media trend researcher. "
            f"Today's date and time is {date_str}.\n\n"
            f"Below are real, current search results about: {topic}\n\n"
            f"{brave_context}\n\n"
            f"Based on these search results, create a concise bullet list of 5-8 trending "
            f"stories, events, or controversies that people are talking about on social media.\n\n"
            f"For each bullet:\n"
            f"- Include the date it happened or started trending (and time if known)\n"
            f"- List items from most recent to oldest\n"
            f"- Include relevant hashtags, names, or viral moments\n"
            f"- Be specific — reference the actual events, people, or takes from the search results\n"
            f"- Prioritize stories from the last 24-48 hours\n\n"
            f"Respond with a concise bullet list only. No introduction or conclusion."
        )
    else:
        # Fallback: no Brave results — let the LM generate from training data
        logger.info("No Brave Search results — falling back to LM-only trending research")
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
            [cli_path, "exec", "--skip-git-repo-check", "--full-auto", "-"],
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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

    # LM-based research (now grounded with Brave Search when available)
    if source in ("lm", "both"):
        lm_ctx = fetch_lm_trending(config, topic)
        if lm_ctx:
            context_parts.append(lm_ctx)

    if not context_parts:
        logger.debug("No trending context found for topic: {}", topic)
        return ""

    combined = "\n\n".join(context_parts)
    logger.debug("Total trending context: {} chars", len(combined))
    return combined
