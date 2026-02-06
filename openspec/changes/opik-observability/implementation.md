# Opik Observability — Implementation Plan

**Proposal Reference ID**: OPIK-001
**Status**: Completed
**Approved**: 2026-02-05
**Completed**: 2026-02-06
**PR**: #4 (feat/all-specs → main)

---

## Prerequisites and Dependencies

### Required Before Starting
- NightWatch v0.1.0 fully implemented and passing all tests
- Opik/Comet Cloud account created (https://www.comet.com/opik)
- Opik API key obtained from Comet Cloud dashboard
- `uv` package manager available for dependency installation

### External Dependencies
- `opik>=1.0.0` -- LLM observability SDK (new dependency to add)
- Comet Cloud service availability for trace ingestion

### Internal Dependencies
- `nightwatch/analyzer.py` -- wrapping the Anthropic client
- `nightwatch/runner.py` -- initialization point for Opik
- `nightwatch/config.py` -- new settings fields

---

## Current State

NightWatch v0.1.0 is fully implemented with:
- `analyzer.py` — Claude agentic loop (creates `anthropic.Anthropic()` client per call)
- `runner.py` — Full pipeline orchestration (11 steps)
- `config.py` — pydantic-settings with all env vars
- `pyproject.toml` — 9 dependencies

The codebase is clean, sync Python, ~1800 lines across 10 files.

---

## Implementation Tasks

### Task 1: Add `opik` dependency (15 minutes)

**File**: `pyproject.toml`

Add `opik` to the dependencies list:

```toml
dependencies = [
    "anthropic>=0.77.0",
    "PyGithub>=2.1.0",
    "httpx>=0.26.0",
    "slack-sdk>=3.27.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
    "certifi",
    "opik>=1.0.0",              # NEW — LLM observability
]
```

Then run: `cd /Users/ahenderson/dev/NightWatch && uv sync`

---

### Task 2: Add Opik config settings (15 minutes)

**File**: `nightwatch/config.py`

Add optional Opik settings to the `Settings` class:

```python
# Optional — Opik observability (disabled if not set)
opik_api_key: str | None = None
opik_workspace: str | None = None
opik_project_name: str = "nightwatch"
opik_enabled: bool = True  # Can disable even if API key is set
```

Opik is **opt-in** — if `OPIK_API_KEY` is not set, tracing is silently disabled.

---

### Task 3: Create `nightwatch/observability.py` (1 hour) -- NEW FILE

Central module that initializes Opik and provides the tracked Anthropic client.

```python
"""Opik observability integration — tracing for Claude API calls and pipeline steps."""

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
        # Return no-op decorator
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
```

**Design decisions**:
- **Graceful fallback**: If `opik` isn't installed or configured, everything works normally — no tracing, no errors.
- **Single initialization point**: `configure_opik()` called once at startup.
- **Wrapper pattern**: `wrap_anthropic_client()` wraps client in-place — caller doesn't change.
- **Decorator factory**: `track_function()` returns a real decorator or no-op based on config.

---

### Task 4: Instrument `analyzer.py` (30 minutes)

**File**: `nightwatch/analyzer.py`

Two changes:

**4a. Wrap the Anthropic client** (line 43):

```python
# Before:
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# After:
from nightwatch.observability import wrap_anthropic_client

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
client = wrap_anthropic_client(client)
```

This automatically traces every `client.messages.create()` call inside the agentic loop — tokens, cost, latency, model, messages, stop reason.

**4b. Add `@track_function` to key functions**:

```python
from nightwatch.observability import track_function

@track_function("analyze_error", tags=["claude", "agentic-loop"])
def analyze_error(error, traces, github_client, newrelic_client):
    ...

@track_function("execute_tool", metadata={"type": "tool_execution"})
def _execute_single_tool(tool_name, tool_input, error, traces, github_client, newrelic_client):
    ...
```

**What this gives us**: Each error analysis becomes a parent span containing nested Claude API call spans and tool execution spans. The full agentic loop is visible in the Opik trace explorer.

---

### Task 5: Instrument `runner.py` (15 minutes)

**File**: `nightwatch/runner.py`

**5a. Initialize Opik at startup** (top of `run()` function):

```python
from nightwatch.observability import configure_opik, track_function

def run(since=None, max_errors=None, ...):
    settings = get_settings()
    start_time = time.time()

    # Initialize Opik tracing (no-op if not configured)
    configure_opik()

    # ... rest of pipeline
```

**5b. Wrap the `run()` function itself**:

We can't use the decorator directly on `run()` because `configure_opik()` happens inside it. Instead, we'll add manual span creation or restructure slightly:

```python
def run(since=None, max_errors=None, ...):
    settings = get_settings()
    start_time = time.time()
    configure_opik()
    return _run_pipeline(since, max_errors, ...)

@track_function("nightwatch_run", tags=["nightly", "pipeline"])
def _run_pipeline(since, max_errors, ...):
    # All existing pipeline code moves here
    ...
```

Alternatively, keep it simpler — just trace `analyze_error` and tool calls (where the LLM cost lives). The runner itself has no LLM calls.

**Recommendation**: Start with option B (just trace analyzer + tools). Add runner-level tracing later if needed.

---

### Task 6: Update `.env.example` (10 minutes)

Add Opik configuration:

```env
# --- Opik Observability (optional) ---
# Sign up at https://www.comet.com/opik to get an API key
# If not set, NightWatch runs without tracing — no impact on functionality
OPIK_API_KEY=                    # Comet Cloud API key
OPIK_WORKSPACE=                  # Comet workspace name
OPIK_PROJECT_NAME=nightwatch     # Project name in Opik dashboard
OPIK_ENABLED=true                # Set to false to disable even with API key
```

---

### Task 7: Run `uv sync` and verify (15 minutes)

```bash
cd /Users/ahenderson/dev/NightWatch
uv sync
./venv/bin/python -c "import opik; print(opik.__version__)"
```

---

## File Change Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `pyproject.toml` | Edit | +1 line (opik dep) |
| `nightwatch/config.py` | Edit | +4 lines (settings) |
| `nightwatch/observability.py` | **New** | ~80 lines |
| `nightwatch/analyzer.py` | Edit | +5 lines (import + wrap + decorators) |
| `nightwatch/runner.py` | Edit | +2 lines (configure_opik call) |
| `.env.example` | Edit | +5 lines |

**Total**: ~97 lines added, 1 new file.

---

## Execution Order

1. `pyproject.toml` → add opik dependency
2. `uv sync` → install it
3. `nightwatch/config.py` → add settings
4. `nightwatch/observability.py` → create new module
5. `nightwatch/analyzer.py` → wrap client + add decorators
6. `nightwatch/runner.py` → add configure_opik() call
7. `.env.example` → add documentation
8. Test with `--dry-run` to verify nothing breaks without Opik key
9. Set `OPIK_API_KEY` in `.env` and run again to verify tracing works
10. Check Opik dashboard for trace data

---

## Testing Strategy

1. **Without Opik configured** (no API key): Run should work identically to before. No errors, no tracing.
2. **With invalid API key**: Should log a warning and continue without tracing.
3. **With valid API key**: Run should complete normally AND show traces in Opik dashboard.
4. **Import test**: `python -c "from nightwatch.observability import configure_opik; print('OK')"` should work even without opik installed (graceful import handling).

---

## Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| `opik` package conflicts with existing deps | Low | Medium | Test `uv sync` first, check for conflicts |
| Tracing adds latency | Very Low | Low | Opik tracing is non-blocking by design |
| Opik Cloud outage | Low | None | Graceful fallback — pipeline continues |
| Privacy concerns (prompts sent to Comet) | Medium | Medium | Document clearly; self-hosted option available |
