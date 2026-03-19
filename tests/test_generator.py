"""Tests for the content generator module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.config import BotConfig
from src.content.generator import _resolve_codex_path, generate_post


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
        "codex": {"cli_path": "/usr/bin/codex", "timeout_seconds": 5},
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
