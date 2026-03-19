"""GIF extraction, Giphy search, and download."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request

from loguru import logger

from src.config import BotConfig

# Matches [gif: some description] anywhere in text (case-insensitive)
_GIF_TAG_RE = re.compile(r"\[gif:\s*(.+?)\]", re.IGNORECASE)


def extract_gif_tag(text: str) -> tuple[str, str | None]:
    """Extract a GIF tag from generated text.

    Returns (cleaned_text, gif_query) where gif_query is None if no tag found.
    Only the first tag is used if multiple are present.
    """
    match = _GIF_TAG_RE.search(text)
    if not match:
        return text, None

    gif_query = match.group(1).strip()
    # Remove the tag from the text and clean up whitespace
    cleaned = text[: match.start()] + text[match.end() :]
    cleaned = re.sub(r"  +", " ", cleaned).strip()

    logger.debug("Extracted GIF tag: {!r} → query: {!r}", match.group(0), gif_query)
    return cleaned, gif_query


def search_gif(query: str, config: BotConfig) -> str | None:
    """Search Giphy for a GIF matching the query. Returns a GIF URL or None."""
    api_key = os.environ.get(config.giphy.api_key_env, "")
    if not api_key:
        logger.warning(
            "Giphy API key not set (env var: {}). Skipping GIF search.",
            config.giphy.api_key_env,
        )
        return None

    encoded_query = urllib.request.quote(query)
    url = (
        f"https://api.giphy.com/v1/gifs/search"
        f"?api_key={api_key}"
        f"&q={encoded_query}"
        f"&limit=1"
        f"&rating={config.giphy.rating}"
    )

    logger.debug("Searching Giphy for: {!r}", query)

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=config.giphy.timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        results = body.get("data", [])
        if not results:
            logger.info("Giphy returned no results for: {!r}", query)
            return None

        gif_url = results[0]["images"]["original"]["url"]
        logger.info("Giphy match for {!r}: {}", query, gif_url)
        return gif_url

    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("Giphy search failed: {}", exc)
        return None


def download_gif(url: str, timeout: int = 10) -> str | None:
    """Download a GIF from a URL to a temporary file. Returns the file path or None."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()

        # Write to a temp file that persists until explicitly deleted
        tmp = tempfile.NamedTemporaryFile(suffix=".gif", delete=False)
        tmp.write(data)
        tmp.close()

        logger.debug("Downloaded GIF ({} bytes) to {}", len(data), tmp.name)
        return tmp.name

    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("GIF download failed: {}", exc)
        return None
