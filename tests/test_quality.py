"""Tests for quality signal feedback loop."""

import tempfile
from pathlib import Path

from nightwatch.quality import QualityTracker


def test_quality_tracker_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        assert qt._signals == []


def test_record_signal():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        qt.record_signal(
            error_class="NoMethodError",
            transaction="UsersController#show",
            confidence=0.85,
            iterations_used=5,
            tokens_used=10000,
            had_file_changes=True,
            had_root_cause=True,
        )
        assert len(qt._signals) == 1
        assert qt._signals[0]["quality_score"] > 0.5


def test_quality_score_computation():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        score = qt._compute_quality_score(0.9, True, True)
        assert score >= 0.9
        score = qt._compute_quality_score(0.1, False, False)
        assert score <= 0.1


def test_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        qt.record_signal(
            error_class="Test",
            transaction="Test#test",
            confidence=0.8,
            iterations_used=3,
            tokens_used=5000,
            had_file_changes=True,
            had_root_cause=True,
        )
        qt.save()

        qt2 = QualityTracker(storage_dir=Path(tmpdir))
        historical = qt2.load_historical()
        assert len(historical) == 1


def test_summary_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        summary = qt.get_summary()
        assert summary["count"] == 0
        assert summary["avg_quality"] == 0.0


def test_summary_with_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        qt = QualityTracker(storage_dir=Path(tmpdir))
        qt.record_signal("Err1", "T1", 0.9, 3, 5000, True, True)
        qt.record_signal("Err2", "T2", 0.3, 8, 15000, False, True)
        summary = qt.get_summary()
        assert summary["count"] == 2
        assert summary["avg_confidence"] > 0
