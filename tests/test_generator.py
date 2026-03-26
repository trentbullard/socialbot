"""Tests for the content generator module."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.config import BotConfig
from src.content.generator import (
    _build_codex_env,
    _resolve_codex_path,
    generate_post,
    generate_reply,
    preview_reply_prompts,
)


def _make_config(**overrides) -> BotConfig:
    base = {
        "content": {
            "tone": ["sarcastic"],
            "topics": ["AI"],
            "style": {"max_length": 280},
            "lean": "test",
            "guidelines": [],
        },
        "generator_backend": "codex",
        "codex": {"cli_path": "/usr/bin/codex", "node_path": "", "timeout_seconds": 5},
    }
    base.update(overrides)
    return BotConfig(**base)


def test_resolve_explicit_path() -> None:
    config = _make_config()
    assert _resolve_codex_path(config) == "/usr/bin/codex"


def test_resolve_auto_detect() -> None:
    config = _make_config(codex={"cli_path": "", "timeout_seconds": 5})
    with patch("shutil.which", return_value="/auto/codex"):
        assert _resolve_codex_path(config) == "/auto/codex"


def test_resolve_not_found() -> None:
    config = _make_config(codex={"cli_path": "", "timeout_seconds": 5})
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="Codex CLI not found"):
            _resolve_codex_path(config)


def test_generate_post_success() -> None:
    config = _make_config()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "this is a generated post about AI lol"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        result = generate_post(config)
        assert result == "this is a generated post about AI lol"


def test_generate_post_uses_codex_exec() -> None:
    config = _make_config()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "short post"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        generate_post(config)

    assert mock_run.call_args.args[0] == [
        "/usr/bin/codex",
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "-",
    ]


def test_build_codex_env_prepends_node_dir() -> None:
    config = _make_config(
        codex={
            "cli_path": "/usr/bin/codex",
            "node_path": "/home/bot/.nvm/versions/node/v22.15.0/bin/node",
            "timeout_seconds": 5,
        }
    )

    with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
        env = _build_codex_env(config)

    assert env["PATH"] == f"/home/bot/.nvm/versions/node/v22.15.0/bin{os.pathsep}/usr/bin"
    assert env["CODEX_NODE_PATH"] == "/home/bot/.nvm/versions/node/v22.15.0/bin/node"


def test_generate_post_passes_codex_env() -> None:
    config = _make_config(
        codex={
            "cli_path": "/usr/bin/codex",
            "node_path": "/home/bot/.nvm/versions/node/v22.15.0/bin/node",
            "timeout_seconds": 5,
        }
    )
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "short post"
    mock_result.stderr = ""

    with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            generate_post(config)

    assert (
        mock_run.call_args.kwargs["env"]["PATH"]
        == f"/home/bot/.nvm/versions/node/v22.15.0/bin{os.pathsep}/usr/bin"
    )


def test_generate_post_uses_explicit_topic_in_prompt() -> None:
    config = _make_config()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "short post"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        generate_post(config, topic="streaming drama")

    assert "Write a single social media post about: streaming drama" in mock_run.call_args.kwargs["input"]


def test_generate_post_trims_long_content() -> None:
    config = _make_config()
    config.content.style.max_length = 20
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "this is way too long to fit in twenty characters obviously"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        result = generate_post(config)
        assert result is not None
        assert len(result) <= 20


def test_generate_post_retries_on_failure() -> None:
    config = _make_config()
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = "error"

    success_result = MagicMock()
    success_result.returncode = 0
    success_result.stdout = "retry success"
    success_result.stderr = ""

    with patch("subprocess.run", side_effect=[fail_result, success_result]):
        result = generate_post(config)
        assert result == "retry success"


def test_generate_post_returns_none_after_all_retries() -> None:
    config = _make_config()
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = "error"

    with patch("subprocess.run", return_value=fail_result):
        result = generate_post(config)
        assert result is None


# ---------------------------------------------------------------------------
# VS Code LM backend tests
# ---------------------------------------------------------------------------

def _make_lm_config(**overrides) -> BotConfig:
    base = {
        "content": {
            "tone": ["sarcastic"],
            "topics": ["AI"],
            "style": {"max_length": 280},
            "lean": "test",
            "guidelines": [],
        },
        "generator_backend": "vscode-lm",
        "vscode_lm": {"host": "127.0.0.1", "port": 19280, "timeout_seconds": 5},
    }
    base.update(overrides)
    return BotConfig(**base)


def test_generate_post_routes_to_vscode_lm() -> None:
    config = _make_lm_config()
    response_body = json.dumps({"content": "ai is just spicy autocomplete", "model": "gpt-4o"}).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = generate_post(config)
        assert result == "ai is just spicy autocomplete"


def test_vscode_lm_trims_long_content() -> None:
    config = _make_lm_config()
    config.content.style.max_length = 15
    response_body = json.dumps({"content": "this is way too long for the limit"}).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = generate_post(config)
        assert result is not None
        assert len(result) <= 15


def test_vscode_lm_returns_none_on_connection_error() -> None:
    config = _make_lm_config()

    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        result = generate_post(config)
        assert result is None


def test_invalid_generator_backend() -> None:
    with pytest.raises(ValueError, match="generator_backend"):
        BotConfig(generator_backend="invalid")


def test_generate_reply_retries_invalid_output() -> None:
    config = _make_config()
    invalid = MagicMock()
    invalid.returncode = 0
    invalid.stdout = "this is way too many words for a quick terse reply"
    invalid.stderr = ""

    valid = MagicMock()
    valid.returncode = 0
    valid.stdout = "fair enough there 😅"
    valid.stderr = ""

    with patch("subprocess.run", side_effect=[invalid, valid]):
        result = generate_reply(
            config,
            comment_text="great point lol",
            sentiment="positive",
            emoji="😅",
        )
        assert result == "fair enough there 😅"


def test_generate_reply_allows_short_acknowledgement() -> None:
    config = _make_config()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "so true 😅"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        result = generate_reply(
            config,
            comment_text="great point lol",
            sentiment="positive",
            emoji="😅",
        )
        assert result == "so true 😅"


def test_generate_reply_rejects_disallowed_emoji() -> None:
    config = _make_config()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "fair enough there 😂"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        result = generate_reply(
            config,
            comment_text="wrong and dumb",
            sentiment="negative",
            emoji="🤡",
        )
        assert result is None


def test_preview_reply_prompts_exposes_comment_context() -> None:
    config = _make_config()
    system_prompt, user_prompt = preview_reply_prompts(
        config,
        comment_text="lol this is actually true",
        sentiment="positive",
        emoji="😅",
    )

    assert "extremely terse, quick human reaction" in system_prompt
    assert "lol this is actually true" in user_prompt
    assert "😅" in user_prompt
