# Social Media Bot — Project Guidelines

## Overview

Automated social media posting bot that generates content via the VS Code Codex extension CLI (not API tokens) and posts on a randomized cadence. The architecture is platform-agnostic with Twitter/X as the first target. All behavioral parameters are driven by YAML configuration — nothing is hardcoded.

**Core loop**: scheduler determines next post time → content generator invokes Codex CLI with assembled prompt → platform adapter posts the result.

**Deployment**: developed and tested locally on Windows (PowerShell), deployed to Ubuntu on DigitalOcean. Both `run.ps1` and `run.sh` entrypoints must be maintained.

## Tech Stack

- **Runtime**: Python 3.12+
- **Config**: YAML (`pyyaml`) with pydantic validation
- **Content generation**: Codex CLI invoked as a subprocess — the same binary used by the VS Code Codex extension. No API tokens consumed.
- **Scheduling**: built-in scheduler with randomized jitter (not cron)
- **Platform integration**: abstract adapter pattern — one adapter per platform

## Project Structure

```
social_media_bot/
├── AGENTS.md
├── config.yaml                 # Active config (gitignored)
├── config.example.yaml         # Template with safe defaults
├── requirements.txt
├── run.ps1                     # PowerShell entrypoint
├── run.sh                      # Bash entrypoint
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI entry point & orchestrator
│   ├── config.py               # Config loading, validation, defaults
│   ├── scheduler.py            # Randomized posting schedule with jitter
│   ├── content/
│   │   ├── __init__.py
│   │   ├── generator.py        # Codex CLI subprocess integration
│   │   └── prompts.py          # Prompt template assembly from config
│   └── platforms/
│       ├── __init__.py
│       ├── base.py             # Abstract PlatformAdapter interface
│       └── twitter.py          # Twitter/X adapter (first implementation)
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_scheduler.py
    ├── test_generator.py
    └── test_prompts.py
```

## Configuration Design

All parameters live in `config.yaml`. Secrets (API keys, tokens) are referenced via environment variables — never stored in config files.

### Key parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `persona.name` | string | Bot persona name. Auto-generated if omitted |
| `persona.handle` | string | Platform handle/username |
| `posting.min_interval_minutes` | int | Minimum time between posts |
| `posting.max_interval_minutes` | int | Maximum time between posts |
| `posting.posts_per_day` | int range | Target daily post count (3-10 default) |
| `content.tone` | list[string] | Tone descriptors: `[sarcastic, dry, blunt, irreverent]` |
| `content.topics` | list[string] | Topic pool to draw from |
| `content.style` | object | Capitalization, punctuation, emoji, gif rules |
| `content.style.max_length` | int | Character limit per post |
| `content.style.capitalization` | string | `minimal` / `normal` / `none` |
| `content.style.punctuation` | string | `minimal` / `normal` |
| `content.style.emoji_probability` | float | 0.0–1.0, how often to include emojis |
| `content.style.gif_probability` | float | 0.0–1.0, how often to include a gif/meme reference |
| `content.lean` | string | Worldview lean descriptor for prompt assembly |
| `content.guidelines` | list[string] | Hard rules for content (e.g., "never be explicitly political") |
| `codex.cli_path` | string | Path to Codex CLI binary. Auto-detected if omitted |
| `codex.model` | string | Model to request from Codex CLI |
| `codex.timeout_seconds` | int | Max time to wait for generation |
| `platform` | string | Active platform adapter name |
| `platform_config` | object | Platform-specific settings (keys from env vars) |
| `logging.level` | string | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## Content Generation

### Persona & voice

The bot is a social media persona — it represents a real person's views but never references that person directly. It reads as a sharp, culturally-aware commenter who:

- Writes brief single posts (never threads)
- Uses sarcastic, dry humor
- Minimal punctuation and capitalization
- Includes humorous emojis and occasional gif/meme references
- Leans edgy conservative grounded in observable reality and statistics
- The lean is **implied through sarcasm and framing**, never stated outright
- Is NOT shock-bait, NOT overtly polarizing, NOT rage-farming
- Goal is organic follower growth through wit, not controversy

### Topic pool

Content draws from current events across these areas (configurable in `config.yaml`):

- AI developments and hype cycles
- Twitch streamer and gaming community drama
- Cultural/media commentary (e.g., forced messaging in entertainment)
- Politics and policy (domestic, delivered through sarcasm)
- Men's experiences and dating culture
- Extremes in social debates (mocking both sides when warranted)
- Crypto culture and memes
- Viral social media moments
- Influencer/creator economy drama
- Pop culture and meme trends

### Generation flow

1. Scheduler fires → picks topic(s) from configured pool (weighted random)
2. `prompts.py` assembles a generation prompt from config: tone + topic + style rules + guidelines + recent post history (avoid repetition)
3. `generator.py` invokes Codex CLI as a subprocess with the assembled prompt
4. Response is validated (length, content policy) and trimmed
5. Platform adapter posts the content

### Codex CLI integration

- Invoked via `subprocess.run()` with the assembled prompt on stdin or as an argument
- The `codex.cli_path` config param allows override; default is auto-detection on `$PATH`
- Timeout enforced to avoid hanging
- Stderr captured for error logging
- If generation fails, log and retry once before skipping the slot

## Platform Adapters

Every adapter implements the `PlatformAdapter` abstract base class:

```python
class PlatformAdapter(ABC):
    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def post(self, content: str, media_url: str | None = None) -> str: ...

    @abstractmethod
    async def validate_credentials(self) -> bool: ...
```

### Anti-bot considerations

- Scheduler uses random jitter between configurable min/max intervals — never posts at fixed intervals
- Human-like timing: slight random delays (seconds) before posting after generation
- Respect platform rate limits — adapters must implement backoff
- User-Agent and session handling should mimic normal client behavior

## Code Conventions

- Type hints on all function signatures and return types
- Pydantic `BaseModel` for config schema and validation
- `dataclasses` for internal data structures where pydantic is overkill
- `async`/`await` for platform I/O (posting, auth); sync is fine for Codex CLI subprocess
- Secrets loaded from env vars via `os.environ` — never from config files, never logged
- Structured logging to stdout via `logging` module with configurable level
- No hardcoded values — if it could change, it's a config parameter
- Keep modules focused: one responsibility per file

## Build & Test

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Dry run (generates content but does not post)
python -m src.main --config config.yaml --dry-run

# Full run
python -m src.main --config config.yaml

# PowerShell entrypoint
.\run.ps1 -Config config.yaml -DryRun

# Bash entrypoint
./run.sh --config config.yaml --dry-run
```

## Implementation Order

When building this project, follow this sequence:

1. Config schema and loading (`config.py` + `config.example.yaml`)
2. Platform adapter interface (`platforms/base.py`)
3. Prompt template system (`content/prompts.py`)
4. Codex CLI integration (`content/generator.py`)
5. Scheduler (`scheduler.py`)
6. Main orchestrator (`main.py`) + entrypoints (`run.ps1`, `run.sh`)
7. Twitter/X adapter (`platforms/twitter.py`)
8. Tests for each module
