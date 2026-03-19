"""Content generation via Codex CLI or VS Code LM proxy."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
import urllib.error

from loguru import logger

from src.config import BotConfig
from src.content.prompts import (
    build_generation_prompt,
    build_system_prompt,
    should_include_emoji,
    should_include_gif,
)


# ---------------------------------------------------------------------------
# Prompt assembly (shared by both backends)
# ---------------------------------------------------------------------------

def _build_prompts(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a generation request."""
    system_prompt = build_system_prompt(config)
    user_prompt = build_generation_prompt(
        config,
        recent_posts=recent_posts,
        include_emoji=should_include_emoji(config),
        include_gif=should_include_gif(config),
        trending_context=trending_context,
    )
    logger.debug("System prompt ({} chars)", len(system_prompt))
    logger.debug("User prompt ({} chars):\n{}", len(user_prompt), user_prompt)
    return system_prompt, user_prompt


def _validate_and_trim(content: str, config: BotConfig) -> str | None:
    """Validate content is non-empty and trim to max length."""
    content = content.strip()
    if not content:
        return None
    max_len = config.content.style.max_length
    if len(content) > max_len:
        content = content[:max_len].rsplit(" ", 1)[0]
    return content


# ---------------------------------------------------------------------------
# Backend: Codex CLI
# ---------------------------------------------------------------------------

def _resolve_codex_path(config: BotConfig) -> str:
    """Return explicit cli_path from config, or auto-detect on PATH."""
    if config.codex.cli_path:
        logger.debug("Using explicit Codex CLI path: {}", config.codex.cli_path)
        return config.codex.cli_path

    for name in ("codex", "codex.exe", "codex-cli", "codex-cli.exe"):
        found = shutil.which(name)
        if found:
            logger.debug("Auto-detected Codex CLI at: {}", found)
            return found

    raise FileNotFoundError(
        "Codex CLI not found on PATH. Set codex.cli_path in config or install the Codex CLI."
    )


def _generate_via_codex(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> str | None:
    """Generate a post using the Codex CLI subprocess."""
    codex_path = _resolve_codex_path(config)
    logger.info("Generating post via Codex CLI at: {}", codex_path)
    system_prompt, user_prompt = _build_prompts(config, recent_posts, trending_context)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    for attempt in range(2):
        try:
            result = subprocess.run(
                [codex_path, "--full-auto", "-"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=config.codex.timeout_seconds,
            )

            if result.returncode != 0:
                logger.warning(
                    "Codex CLI exited with code {} (attempt {}): {}",
                    result.returncode,
                    attempt + 1,
                    result.stderr.strip(),
                )
                continue

            content = _validate_and_trim(result.stdout, config)
            if content is None:
                logger.warning("Codex returned empty content (attempt {})", attempt + 1)
                continue

            logger.info("Generated post ({} chars): {}", len(content), content[:80])
            return content

        except subprocess.TimeoutExpired:
            logger.warning(
                "Codex CLI timed out after {}s (attempt {})",
                config.codex.timeout_seconds,
                attempt + 1,
            )
        except OSError as exc:
            logger.error("Failed to run Codex CLI: {}", exc)
            return None

    logger.error("Codex content generation failed after retries")
    return None


# ---------------------------------------------------------------------------
# Backend: VS Code LM Proxy
# ---------------------------------------------------------------------------

def _generate_via_vscode_lm(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> str | None:
    """Generate a post via the VS Code LM proxy HTTP server."""
    host = config.vscode_lm.host
    port = config.vscode_lm.port
    url = f"http://{host}:{port}/generate"

    system_prompt, user_prompt = _build_prompts(config, recent_posts, trending_context)

    payload = json.dumps({
        "prompt": user_prompt,
        "systemPrompt": system_prompt,
    }).encode("utf-8")

    logger.info("Generating post via VS Code LM proxy at {}:{}", host, port)

    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=config.vscode_lm.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            raw_content = body.get("content", "")
            model_used = body.get("model", "unknown")
            logger.debug("LM proxy responded with model: {}", model_used)

            content = _validate_and_trim(raw_content, config)
            if content is None:
                logger.warning("LM proxy returned empty content (attempt {})", attempt + 1)
                continue

            logger.info("Generated post ({} chars): {}", len(content), content[:80])
            return content

        except urllib.error.URLError as exc:
            logger.warning(
                "LM proxy connection failed (attempt {}): {}",
                attempt + 1,
                exc.reason,
            )
        except TimeoutError:
            logger.warning(
                "LM proxy timed out after {}s (attempt {})",
                config.vscode_lm.timeout_seconds,
                attempt + 1,
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Invalid response from LM proxy: {}", exc)
            return None

    logger.error("VS Code LM content generation failed after retries")
    return None


# ---------------------------------------------------------------------------
# Public API — routes to the configured backend
# ---------------------------------------------------------------------------

def generate_post(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> str | None:
    """Generate a single post using the configured backend.

    Returns the generated text, or None if generation fails.
    """
    backend = config.generator_backend
    logger.debug("Using generator backend: {}", backend)

    if backend == "vscode-lm":
        return _generate_via_vscode_lm(config, recent_posts, trending_context)
    else:
        return _generate_via_codex(config, recent_posts, trending_context)
