"""Configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """NightWatch configuration loaded from environment variables."""

    # Required — API keys and identifiers
    anthropic_api_key: str
    github_token: str
    github_repo: str  # e.g. "g2crowd/ue"
    new_relic_api_key: str
    new_relic_account_id: str
    new_relic_app_name: str
    slack_bot_token: str
    slack_notify_user: str  # Slack display name to DM

    # Optional — with defaults
    nightwatch_max_errors: int = 5
    nightwatch_max_issues: int = 3
    nightwatch_since: str = "10 minutes"
    nightwatch_model: str = "claude-sonnet-4-5-20250929"
    nightwatch_max_iterations: int = 15
    nightwatch_dry_run: bool = False
    nightwatch_max_open_issues: int = 10
    github_base_branch: str = "main"

    # Multi-pass analysis (Ralph pattern: retry low-confidence with seed knowledge)
    nightwatch_multi_pass_enabled: bool = True
    nightwatch_max_passes: int = 2

    # Run context accumulation (Ralph pattern: cross-error knowledge sharing)
    nightwatch_run_context_enabled: bool = True
    nightwatch_run_context_max_chars: int = 1500

    # Quality gate (Ralph pattern: validate before committing)
    nightwatch_quality_gate_enabled: bool = True
    nightwatch_quality_gate_correction: bool = True

    # Compound engineering (knowledge compounding across runs)
    nightwatch_knowledge_dir: str = "nightwatch/knowledge"
    nightwatch_compound_enabled: bool = True

    # Optional — Opik observability (disabled if not set)
    opik_api_key: str | None = None
    opik_workspace: str | None = None
    opik_project_name: str = "nightwatch"
    opik_enabled: bool = True  # Can disable even if API key is set

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings singleton."""
    return Settings()
