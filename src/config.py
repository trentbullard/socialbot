"""Configuration loading and validation via Pydantic models."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator


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


class PromptingConfig(BaseModel):
    variation_modes: list[str] = Field(
        default_factory=lambda: [
            "observation",
            "prediction",
            "contrast",
            "callout",
            "deadpan",
            "receipt",
            "one-liner",
            "question-like hook without asking a question",
        ]
    )
    discouraged_patterns: list[str] = Field(
        default_factory=lambda: [
            "<topic> is like <reference>",
            "generic summary ending",
            "list of broad generalities",
            "forced pop-culture analogy",
        ]
    )
    engagement_goals: list[str] = Field(
        default_factory=lambda: [
            "lead with a concrete observation",
            "make the reader feel they noticed something true",
            "prefer specific nouns over abstractions",
            "invite internal agreement or disagreement without explicit CTA",
        ]
    )
    engagement_anti_patterns: list[str] = Field(
        default_factory=lambda: [
            "do not sound like engagement bait",
            "avoid sounding like a take-generator",
            "avoid explaining the joke",
        ]
    )
    affinity_mode: str = "lean_charitable_people"
    affinity_instructions: list[str] = Field(
        default_factory=lambda: [
            "if a person appears broadly aligned with the configured worldview, avoid cheap negative swipes",
            "default to neutral or charitable framing unless there is a clear factual reason to criticize",
            "do not praise blindly",
        ]
    )
    recent_posts_window: int = Field(5, ge=1)

    @field_validator("affinity_mode")
    @classmethod
    def valid_affinity_mode(cls, v: str) -> str:
        allowed = {"off", "lean_charitable_people"}
        if v not in allowed:
            raise ValueError(f"content.prompting.affinity_mode must be one of {allowed}")
        return v


class ContentConfig(BaseModel):
    tone: list[str] = ["sarcastic", "dry", "blunt", "irreverent"]
    topics: list[str] = []
    style: StyleConfig = StyleConfig()
    lean: str = ""
    guidelines: list[str] = []
    trending: TrendingConfig = TrendingConfig()
    prompting: PromptingConfig = PromptingConfig()


class CodexConfig(BaseModel):
    cli_path: str = ""
    node_path: str = ""
    model: str = ""
    timeout_seconds: int = 300


class VsCodeLmConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 19280
    timeout_seconds: int = 300


class BraveSearchConfig(BaseModel):
    api_key_env: str = "BRAVE_API_KEY"
    timeout_seconds: int = 15
    freshness: str = "pd"  # pd=past day, pw=past week, pm=past month
    count: int = 10

    @field_validator("freshness")
    @classmethod
    def valid_freshness(cls, v: str) -> str:
        allowed = {"pd", "pw", "pm", "py", ""}
        if v not in allowed:
            raise ValueError(f"brave_search.freshness must be one of {allowed}")
        return v


class GiphyConfig(BaseModel):
    api_key_env: str = "GIPHY_API_KEY"
    rating: str = "pg-13"
    timeout_seconds: int = 10

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, v: str) -> str:
        allowed = {"g", "pg", "pg-13", "r"}
        if v not in allowed:
            raise ValueError(f"giphy.rating must be one of {allowed}")
        return v


class PlatformCredentialConfig(BaseModel):
    """Maps credential names to environment variable names."""

    model_config = {"extra": "allow"}


class LoggingConfig(BaseModel):
    level: str = "INFO"
    timezone: str = "local"
    log_next_post_countdown: bool = True

    @field_validator("level")
    @classmethod
    def valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"logging.level must be one of {allowed}")
        return v_upper

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, v: str) -> str:
        tz_name = v.strip()
        if not tz_name:
            raise ValueError("logging.timezone must not be empty")
        if tz_name.lower() == "local":
            return "local"
        try:
            now_utc = datetime.now(ZoneInfo("UTC"))
            now_utc.astimezone(ZoneInfo(tz_name))
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"logging.timezone must be a valid IANA timezone or 'local': {tz_name}") from exc
        return tz_name


class EngagementRepliesConfig(BaseModel):
    enabled: bool = False
    min_replies_per_post: int = Field(5, ge=1)
    max_replies_per_post: int = Field(8, ge=1)
    window_minutes: int = Field(120, ge=1)
    poll_interval_seconds_min: int = Field(30, ge=1)
    poll_interval_seconds_max: int = Field(90, ge=1)
    reply_delay_seconds_min: int = Field(8, ge=0)
    reply_delay_seconds_max: int = Field(40, ge=0)
    allow_neutral_as_positive: bool = True
    max_replies_per_user_per_post: int = Field(1, ge=1)
    positive_emojis: list[str] = Field(default_factory=lambda: ["😅", "🤣"])
    negative_emojis: list[str] = Field(default_factory=lambda: ["🥴", "🤡"])
    positive_emoji_probability: float = Field(0.35, ge=0.0, le=1.0)
    negative_emoji_probability: float = Field(0.5, ge=0.0, le=1.0)
    skip_if_contains_links: bool = True
    skip_if_author_is_self: bool = True

    @model_validator(mode="after")
    def validate_ranges(self) -> "EngagementRepliesConfig":
        if self.max_replies_per_post < self.min_replies_per_post:
            raise ValueError("engagement.replies.max_replies_per_post must be >= min_replies_per_post")
        if self.poll_interval_seconds_max < self.poll_interval_seconds_min:
            raise ValueError(
                "engagement.replies.poll_interval_seconds_max must be >= poll_interval_seconds_min"
            )
        if self.reply_delay_seconds_max < self.reply_delay_seconds_min:
            raise ValueError(
                "engagement.replies.reply_delay_seconds_max must be >= reply_delay_seconds_min"
            )
        if not self.positive_emojis:
            raise ValueError("engagement.replies.positive_emojis must not be empty")
        if not self.negative_emojis:
            raise ValueError("engagement.replies.negative_emojis must not be empty")
        return self


class EngagementConfig(BaseModel):
    state_path: str = ".bot_state/engagement_state.json"
    replies: EngagementRepliesConfig = EngagementRepliesConfig()

    @field_validator("state_path")
    @classmethod
    def valid_state_path(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("engagement.state_path must not be empty")
        return v


class BotConfig(BaseModel):
    """Root configuration model."""

    persona: PersonaConfig = PersonaConfig()
    posting: PostingConfig = PostingConfig()
    content: ContentConfig = ContentConfig()
    generator_backend: str = "codex"
    codex: CodexConfig = CodexConfig()
    vscode_lm: VsCodeLmConfig = VsCodeLmConfig()
    brave_search: BraveSearchConfig = BraveSearchConfig()
    giphy: GiphyConfig = GiphyConfig()
    engagement: EngagementConfig = EngagementConfig()
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
