"""Run history persistence for cross-run pattern analysis."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("nightwatch.history")

_HISTORY_DIR = Path.home() / ".nightwatch"


def _get_history_file() -> Path:
    """Get the JSONL history file path."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return _HISTORY_DIR / "run_history.jsonl"


def save_run(report_data: dict[str, Any]) -> None:
    """Append a run report to history as a JSON line."""
    history_file = _get_history_file()
    entry = {"timestamp": datetime.now().isoformat(), **report_data}
    try:
        with open(history_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"Saved run to history: {history_file}")
    except Exception as e:
        logger.warning(f"Failed to save run history: {e}")


def load_history(days: int = 30, max_entries: int = 100) -> list[dict[str, Any]]:
    """Load recent run history from JSONL file."""
    history_file = _get_history_file()
    if not history_file.exists():
        return []

    cutoff = datetime.now() - timedelta(days=days)
    entries: list[dict[str, Any]] = []

    try:
        with open(history_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if ts:
                        entry_time = datetime.fromisoformat(ts)
                        if entry_time >= cutoff:
                            entries.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception as e:
        logger.warning(f"Failed to load run history: {e}")

    return entries[-max_entries:]
