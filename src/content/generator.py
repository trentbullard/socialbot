"""Content generation via Codex CLI or VS Code LM proxy."""

from __future__ import annotations

from collections.abc import Callable
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request

from loguru import logger

from src.config import BotConfig
from src.content.prompts import (
    build_generation_prompt,
    build_reply_generation_prompt,
    build_reply_system_prompt,
    build_system_prompt,
    should_include_emoji,
    should_include_gif,
)

MAX_REPLY_WORDS = 8
MAX_REPLY_CHARS = 48


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


def _build_reply_prompts(
    config: BotConfig,
    *,
    comment_text: str,
    sentiment: str,
    emoji: str | None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a reply generation request."""
    system_prompt = build_reply_system_prompt(config)
    user_prompt = build_reply_generation_prompt(
        comment_text,
        sentiment=sentiment,
        emoji=emoji,
    )
    logger.debug("Reply system prompt ({} chars):\n{}", len(system_prompt), system_prompt)
    logger.debug("Reply user prompt ({} chars):\n{}", len(user_prompt), user_prompt)
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


def _validate_reply_content(content: str, *, allowed_emojis: list[str]) -> str | None:
    """Validate a generated reply stays terse and non-conversational."""
    content = content.strip()
    if not content or "\n" in content:
        return None
    if re.search(r"(https?://|www\.|#|@)", content, flags=re.IGNORECASE):
        return None
    if "?" in content:
        return None

    normalized = content
    for emoji in allowed_emojis:
        normalized = normalized.replace(emoji, " ")
    if any(ord(char) > 127 for char in normalized):
        return None

    words = re.findall(r"[A-Za-z0-9']+", normalized)
    if not words or len(words) > MAX_REPLY_WORDS:
        return None
    if len(content) > MAX_REPLY_CHARS:
        return None
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


def _run_codex_prompt(
    config: BotConfig,
    *,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
    log_label: str,
    validator: Callable[[str], str | None],
) -> str | None:
    """Send an arbitrary prompt to the Codex CLI backend."""
    codex_path = _resolve_codex_path(config)
    logger.info("Generating {} via Codex CLI at: {}", log_label, codex_path)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    for attempt in range(2):
        try:
            result = subprocess.run(
                [codex_path, "exec", "--skip-git-repo-check", "--full-auto", "-"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            if result.returncode != 0:
                logger.warning(
                    "Codex CLI exited with code {} (attempt {}): {}",
                    result.returncode,
                    attempt + 1,
                    result.stderr.strip(),
                )
                continue

            content = validator(result.stdout)
            if content is None:
                logger.warning("Codex returned invalid {} content (attempt {})", log_label, attempt + 1)
                continue

            logger.info("Generated {} ({} chars): {}", log_label, len(content), content[:80])
            return content

        except subprocess.TimeoutExpired:
            logger.warning(
                "Codex CLI timed out after {}s (attempt {})",
                timeout_seconds,
                attempt + 1,
            )
        except OSError as exc:
            logger.error("Failed to run Codex CLI: {}", exc)
            return None

    logger.error("Codex {} generation failed after retries", log_label)
    return None


# ---------------------------------------------------------------------------
# Backend: VS Code LM Proxy
# ---------------------------------------------------------------------------

def _run_vscode_prompt(
    config: BotConfig,
    *,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
    log_label: str,
    validator: Callable[[str], str | None],
) -> str | None:
    """Send an arbitrary prompt to the VS Code LM proxy backend."""
    host = config.vscode_lm.host
    port = config.vscode_lm.port
    url = f"http://{host}:{port}/generate"

    payload = json.dumps({
        "prompt": user_prompt,
        "systemPrompt": system_prompt,
    }).encode("utf-8")

    logger.info("Generating {} via VS Code LM proxy at {}:{}", log_label, host, port)

    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            raw_content = body.get("content", "")
            model_used = body.get("model", "unknown")
            logger.debug("LM proxy responded with model: {}", model_used)

            content = validator(raw_content)
            if content is None:
                logger.warning("LM proxy returned invalid {} content (attempt {})", log_label, attempt + 1)
                continue

            logger.info("Generated {} ({} chars): {}", log_label, len(content), content[:80])
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
                timeout_seconds,
                attempt + 1,
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Invalid response from LM proxy: {}", exc)
            return None

    logger.error("VS Code LM {} generation failed after retries", log_label)
    return None


def _generate_via_codex(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> str | None:
    """Generate a post using the Codex CLI subprocess."""
    system_prompt, user_prompt = _build_prompts(config, recent_posts, trending_context)
    return _run_codex_prompt(
        config,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_seconds=config.codex.timeout_seconds,
        log_label="post",
        validator=lambda output: _validate_and_trim(output, config),
    )


def _generate_via_vscode_lm(
    config: BotConfig,
    recent_posts: list[str] | None = None,
    trending_context: str = "",
) -> str | None:
    """Generate a post via the VS Code LM proxy HTTP server."""
    system_prompt, user_prompt = _build_prompts(config, recent_posts, trending_context)
    return _run_vscode_prompt(
        config,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_seconds=config.vscode_lm.timeout_seconds,
        log_label="post",
        validator=lambda output: _validate_and_trim(output, config),
    )


def generate_reply(
    config: BotConfig,
    *,
    comment_text: str,
    sentiment: str,
    emoji: str | None = None,
) -> str | None:
    """Generate a terse reply to a comment using the configured backend."""
    system_prompt, user_prompt = _build_reply_prompts(
        config,
        comment_text=comment_text,
        sentiment=sentiment,
        emoji=emoji,
    )
    allowed_emojis = (
        config.engagement.replies.positive_emojis
        + config.engagement.replies.negative_emojis
    )

    if config.generator_backend == "vscode-lm":
        return _run_vscode_prompt(
            config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=config.vscode_lm.timeout_seconds,
            log_label="reply",
            validator=lambda output: _validate_reply_content(output, allowed_emojis=allowed_emojis),
        )

    return _run_codex_prompt(
        config,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_seconds=config.codex.timeout_seconds,
        log_label="reply",
        validator=lambda output: _validate_reply_content(output, allowed_emojis=allowed_emojis),
    )


def preview_reply_prompts(
    config: BotConfig,
    *,
    comment_text: str,
    sentiment: str,
    emoji: str | None = None,
) -> tuple[str, str]:
    """Build reply prompts for inspection without generating a reply."""
    return _build_reply_prompts(
        config,
        comment_text=comment_text,
        sentiment=sentiment,
        emoji=emoji,
    )


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
