"""Configuration loading and validation via Pydantic models."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from loguru import logger
from pydantic import BaseModel, Field, field_validator


class PersonaConfig(BaseModel):
    name: str = ""
    handle: str = ""


class PostingConfig(BaseModel):
    min_interval_minutes: int = 90
    max_interval_minutes: int = 300
    posts_per_day_min: int = 3
    posts_per_day_max: int = 10
    jitter_seconds_min: int = 5
    jitter_seconds_max: int = 45

    @field_validator("max_interval_minutes")
    @classmethod
    def max_gte_min(cls, v: int, info) -> int:
        min_val = info.data.get("min_interval_minutes", 0)
        if v < min_val:
            raise ValueError("max_interval_minutes must be >= min_interval_minutes")
        return v


class StyleConfig(BaseModel):
    max_length: int = 280
    capitalization: str = "minimal"
    punctuation: str = "minimal"
    emoji_probability: float = Field(0.4, ge=0.0, le=1.0)
    gif_probability: float = Field(0.15, ge=0.0, le=1.0)


class TrendingConfig(BaseModel):
    enabled: bool = False
    source: str = "lm"
    max_results: int = 10
    timeout_seconds: int = 300

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: str) -> str:
        allowed = {"platform", "lm", "both"}
        if v not in allowed:
            raise ValueError(f"trending.source must be one of {allowed}")
        return v


class ContentConfig(BaseModel):
    tone: list[str] = ["sarcastic", "dry", "blunt", "irreverent"]
    topics: list[str] = []
    style: StyleConfig = StyleConfig()
    lean: str = ""
    guidelines: list[str] = []
    trending: TrendingConfig = TrendingConfig()


class CodexConfig(BaseModel):
    cli_path: str = ""
    model: str = ""
    timeout_seconds: int = 300


class VsCodeLmConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 19280
    timeout_seconds: int = 300


class PlatformCredentialConfig(BaseModel):
    """Maps credential names to environment variable names."""

    model_config = {"extra": "allow"}


class LoggingConfig(BaseModel):
    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"logging.level must be one of {allowed}")
        return v_upper


class BotConfig(BaseModel):
    """Root configuration model."""

    persona: PersonaConfig = PersonaConfig()
    posting: PostingConfig = PostingConfig()
    content: ContentConfig = ContentConfig()
    generator_backend: str = "codex"
    codex: CodexConfig = CodexConfig()
    vscode_lm: VsCodeLmConfig = VsCodeLmConfig()
    platform: str = "twitter"
    platform_config: dict[str, dict[str, str]] = {}
    logging: LoggingConfig = LoggingConfig()

    @field_validator("generator_backend")
    @classmethod
    def valid_backend(cls, v: str) -> str:
        allowed = {"codex", "vscode-lm"}
        if v not in allowed:
            raise ValueError(f"generator_backend must be one of {allowed}")
        return v

    def get_platform_credentials(self) -> dict[str, str]:
        """Resolve platform credentials from environment variables."""
        cred_map = self.platform_config.get(self.platform, {})
        resolved: dict[str, str] = {}
        for key, env_var in cred_map.items():
            value = os.environ.get(env_var, "")
            if not value:
                raise EnvironmentError(
                    f"Required env var '{env_var}' for platform credential '{key}' is not set"
                )
            resolved[key] = value
        return resolved


def load_config(path: str | Path) -> BotConfig:
    """Load and validate configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    logger.debug("Loading config from {}", path)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping at the top level")

    return BotConfig(**raw)
