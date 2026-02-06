"""Quality signal feedback loop — tracks analysis quality over time."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("nightwatch.quality")


class QualityTracker:
    """Tracks quality signals from NightWatch analyses for feedback loops."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or Path.home() / ".nightwatch" / "quality"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._signals: list[dict[str, Any]] = []

    def record_signal(
        self,
        error_class: str,
        transaction: str,
        confidence: float,
        iterations_used: int,
        tokens_used: int,
        had_file_changes: bool,
        had_root_cause: bool,
    ) -> None:
        """Record a quality signal from an analysis."""
        signal = {
            "timestamp": datetime.now().isoformat(),
            "error_class": error_class,
            "transaction": transaction,
            "confidence": confidence,
            "iterations_used": iterations_used,
            "tokens_used": tokens_used,
            "had_file_changes": had_file_changes,
            "had_root_cause": had_root_cause,
            "quality_score": self._compute_quality_score(
                confidence, had_file_changes, had_root_cause
            ),
        }
        self._signals.append(signal)

    def _compute_quality_score(
        self, confidence: float, had_file_changes: bool, had_root_cause: bool
    ) -> float:
        """Compute a quality score from 0.0 to 1.0."""
        score = confidence * 0.5
        if had_file_changes:
            score += 0.25
        if had_root_cause:
            score += 0.25
        return min(score, 1.0)

    def save(self) -> None:
        """Save quality signals to disk."""
        if not self._signals:
            return
        filename = f"signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self._storage_dir / filename
        filepath.write_text(json.dumps(self._signals, indent=2))
        logger.info(f"Saved {len(self._signals)} quality signals to {filepath}")

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of quality signals from this run."""
        if not self._signals:
            return {"count": 0, "avg_quality": 0.0, "avg_confidence": 0.0}

        scores = [s["quality_score"] for s in self._signals]
        confidences = [s["confidence"] for s in self._signals]
        tokens = [s["tokens_used"] for s in self._signals]

        return {
            "count": len(self._signals),
            "avg_quality": round(sum(scores) / len(scores), 3),
            "avg_confidence": round(sum(confidences) / len(confidences), 3),
            "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else 0,
            "high_quality_count": sum(1 for s in scores if s >= 0.7),
            "low_quality_count": sum(1 for s in scores if s < 0.3),
        }

    def load_historical(self, days: int = 30) -> list[dict[str, Any]]:
        """Load historical quality signals."""
        all_signals: list[dict[str, Any]] = []
        for f in sorted(self._storage_dir.glob("signals_*.json")):
            try:
                signals = json.loads(f.read_text())
                all_signals.extend(signals)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load quality signals from {f}: {e}")
        return all_signals
