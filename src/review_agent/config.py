"""
config.py — centralised settings for code-review-agent.

All values come from environment variables (or a .env file).
Pydantic-settings validates types and gives clear error messages when
something is missing.

Usage anywhere in the codebase:
    from review_agent.config import settings
    model = settings.review_model
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings, loaded from environment / .env."""

    # ── GitHub ───────────────────────────────────────────────────────────────
    github_token: str
    """Personal access token with `repo` + `pull_requests` scopes."""

    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str
    """API key for Claude — never logged or committed."""

    review_model: str = "claude-3-5-haiku-20241022"
    """Model used for the three reasoning passes.
    Haiku = fast & cheap (good for CI).  Sonnet = deeper reasoning."""

    # ── Behaviour ─────────────────────────────────────────────────────────────
    post_to_github: bool = True
    """When True, the agent posts findings as a real GitHub PR review.
    Set to False for a local dry-run (findings printed to stdout only)."""

    max_files_per_pr: int = 50
    """Skip PRs with more changed files than this to avoid huge context windows."""

    # ── pydantic-settings config ───────────────────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",          # loads .env automatically if present
        env_file_encoding="utf-8",
        case_sensitive=False,     # GITHUB_TOKEN and github_token both work
        extra="ignore",           # silently skip unknown env vars
    )


# Single shared instance — import this everywhere.
settings = Settings()  # type: ignore[call-arg]
