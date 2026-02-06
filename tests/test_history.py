"""Tests for nightwatch.history module."""

from __future__ import annotations

import json
from unittest.mock import patch

from nightwatch.history import load_history, save_run


def test_save_run_creates_jsonl(tmp_path):
    """save_run appends valid JSONL."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"errors_analyzed": [{"error_class": "TestError"}]})

    assert history_file.exists()
    lines = history_file.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert "timestamp" in data
    assert data["errors_analyzed"][0]["error_class"] == "TestError"


def test_save_run_appends(tmp_path):
    """Multiple save_run calls append separate lines."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"run": 1})
        save_run({"run": 2})
        save_run({"run": 3})

    lines = history_file.read_text().strip().split("\n")
    assert len(lines) == 3


def test_load_history_empty(tmp_path):
    """load_history returns empty list when no file exists."""
    history_file = tmp_path / "nonexistent.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        result = load_history()
    assert result == []


def test_load_history_round_trip(tmp_path):
    """save_run → load_history round-trip preserves data."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"error_count": 5, "errors_analyzed": []})
        save_run({"error_count": 3, "errors_analyzed": []})
        entries = load_history(days=1)

    assert len(entries) == 2
    assert entries[0]["error_count"] == 5
    assert entries[1]["error_count"] == 3


def test_load_history_max_entries(tmp_path):
    """load_history respects max_entries limit."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        for i in range(10):
            save_run({"run": i})
        entries = load_history(days=1, max_entries=3)

    assert len(entries) == 3
    # Should be the last 3 entries
    assert entries[0]["run"] == 7
    assert entries[2]["run"] == 9


def test_load_history_skips_malformed_lines(tmp_path):
    """load_history skips malformed JSON lines gracefully."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"run": 1})
    # Inject bad line
    with open(history_file, "a") as f:
        f.write("THIS IS NOT JSON\n")
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"run": 2})
        entries = load_history(days=1)

    assert len(entries) == 2


def test_load_history_skips_empty_lines(tmp_path):
    """load_history skips blank lines."""
    history_file = tmp_path / "run_history.jsonl"
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"run": 1})
    with open(history_file, "a") as f:
        f.write("\n\n\n")
    with patch("nightwatch.history._get_history_file", return_value=history_file):
        save_run({"run": 2})
        entries = load_history(days=1)

    assert len(entries) == 2
