"""Opik observability integration — opt-in tracing for Claude API calls and pipeline steps."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from nightwatch.config import get_settings

logger = logging.getLogger("nightwatch.observability")

_opik_configured = False


def configure_opik() -> bool:
    """Initialize Opik if credentials are available.

    Returns True if Opik is enabled and configured, False otherwise.
    Called once at startup from runner.py.
    """
    global _opik_configured
    settings = get_settings()

    if not settings.opik_enabled or not settings.opik_api_key:
        logger.debug("Opik disabled (no API key or opik_enabled=False)")
        return False

    try:
        import opik

        opik.configure(
            api_key=settings.opik_api_key,
            workspace=settings.opik_workspace,
            use_local=False,
        )
        _opik_configured = True
        logger.info(f"Opik enabled — project: {settings.opik_project_name}")
        return True
    except Exception as e:
        logger.warning(f"Opik initialization failed (continuing without tracing): {e}")
        return False


def wrap_anthropic_client(client: anthropic.Anthropic) -> anthropic.Anthropic:
    """Wrap an Anthropic client with Opik tracing if configured.

    If Opik is not configured, returns the client unchanged.
    """
    if not _opik_configured:
        return client

    try:
        from opik.integrations.anthropic import track_anthropic

        settings = get_settings()
        return track_anthropic(client, project_name=settings.opik_project_name)
    except Exception as e:
        logger.warning(f"Failed to wrap Anthropic client with Opik: {e}")
        return client


def track_function(name: str | None = None, **kwargs: Any):
    """Decorator that adds Opik tracing if configured.

    If Opik is not configured, returns a no-op decorator.
    Usage:
        @track_function("analyze_error", tags=["claude"])
        def analyze_error(...):
            ...
    """
    if not _opik_configured:

        def noop_decorator(func):
            return func

        return noop_decorator

    try:
        from opik import track

        return track(name=name, **kwargs)
    except Exception:

        def noop_decorator(func):
            return func

        return noop_decorator
