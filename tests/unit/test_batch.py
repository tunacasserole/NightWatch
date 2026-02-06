"""Tests for nightwatch.batch — batch triage via Anthropic Message Batches API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from nightwatch.batch import BATCH_STATE_DIR, BatchAnalyzer, TriageResult
from nightwatch.types.core import ErrorGroup


def _make_error(
    error_class: str = "NoMethodError",
    transaction: str = "Controller/users/show",
    message: str = "undefined method 'foo'",
    occurrences: int = 10,
) -> ErrorGroup:
    return ErrorGroup(
        error_class=error_class,
        transaction=transaction,
        message=message,
        occurrences=occurrences,
        last_seen="2025-01-01T00:00:00Z",
    )


@pytest.fixture()
def mock_settings():
    with patch("nightwatch.batch.get_settings") as mock:
        mock.return_value = MagicMock(
            anthropic_api_key="test-key",
            nightwatch_model="claude-sonnet-4-5-20250929",
        )
        yield mock


@pytest.fixture()
def mock_anthropic():
    with patch("nightwatch.batch.anthropic.Anthropic") as mock:
        yield mock


class TestSubmitBatch:
    def test_submit_batch_creates_requests(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """submit_batch sends correct Request objects to the batches API."""
        mock_client = mock_anthropic.return_value
        mock_batch = MagicMock()
        mock_batch.id = "batch_abc123"
        mock_client.messages.batches.create.return_value = mock_batch

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            errors = [_make_error(), _make_error(error_class="RuntimeError")]
            batch_id = analyzer.submit_batch(errors, traces_map={})

        assert batch_id == "batch_abc123"

        call_kwargs = mock_client.messages.batches.create.call_args
        requests = call_kwargs.kwargs.get("requests") or call_kwargs[1].get(
            "requests"
        )
        assert len(requests) == 2
        assert requests[0]["custom_id"].startswith("triage-0-")
        assert requests[1]["custom_id"].startswith("triage-1-")
        assert requests[0]["params"]["max_tokens"] == 512

    def test_submit_batch_saves_state_file(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """submit_batch writes a JSON state file for later collection."""
        mock_client = mock_anthropic.return_value
        mock_batch = MagicMock()
        mock_batch.id = "batch_xyz"
        mock_client.messages.batches.create.return_value = mock_batch

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            analyzer.submit_batch([_make_error()], traces_map={})

        state_file = tmp_path / "batch_xyz.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["batch_id"] == "batch_xyz"
        assert state["error_count"] == 1
        assert "triage-0-NoMethodError" in state["custom_id_map"]

    def test_submit_batch_with_traces(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """submit_batch includes trace data in the prompt when available."""
        mock_client = mock_anthropic.return_value
        mock_batch = MagicMock()
        mock_batch.id = "batch_traces"
        mock_client.messages.batches.create.return_value = mock_batch

        error = _make_error()
        trace_data = MagicMock()
        trace_data.transaction_errors = [
            {"error.class": "NoMethodError", "error.message": "test"}
        ]
        trace_data.error_traces = []

        traces_map = {f"{error.error_class}:{error.transaction}": trace_data}

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            analyzer.submit_batch([error], traces_map=traces_map)

        call_kwargs = mock_client.messages.batches.create.call_args
        requests = call_kwargs.kwargs.get("requests") or call_kwargs[1].get(
            "requests"
        )
        prompt = requests[0]["params"]["messages"][0]["content"]
        assert "Transaction Errors" in prompt


class TestPollResults:
    def test_poll_results_success(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """poll_results returns parsed TriageResult objects."""
        mock_client = mock_anthropic.return_value

        # Mock batch status
        mock_batch = MagicMock()
        mock_batch.processing_status = "ended"
        mock_batch.request_counts.succeeded = 1
        mock_batch.request_counts.errored = 0
        mock_client.messages.batches.retrieve.return_value = mock_batch

        # Mock result
        mock_result = MagicMock()
        mock_result.custom_id = "triage-0-NoMethodError"
        mock_result.result.type = "succeeded"
        text_block = MagicMock()
        text_block.text = json.dumps(
            {
                "severity": "high",
                "likely_root_cause": "Missing method on nil object",
                "needs_deep_investigation": True,
                "fix_category": "code_bug",
            }
        )
        mock_result.result.message.content = [text_block]
        mock_client.messages.batches.results.return_value = [mock_result]

        # Write state file
        state = {
            "batch_id": "batch_poll",
            "submitted_at": "2025-01-01T00:00:00",
            "error_count": 1,
            "custom_id_map": {
                "triage-0-NoMethodError": {
                    "error_class": "NoMethodError",
                    "transaction": "Controller/users/show",
                    "index": 0,
                }
            },
        }
        state_file = tmp_path / "batch_poll.json"
        state_file.write_text(json.dumps(state))

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            results = analyzer.poll_results("batch_poll", poll_interval=0)

        assert len(results) == 1
        assert results[0].severity == "high"
        assert results[0].needs_deep_investigation is True
        assert results[0].fix_category == "code_bug"
        assert results[0].error.error_class == "NoMethodError"

    def test_poll_results_errored_defaults_to_investigate(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """Errored batch results default to needs_deep_investigation=True."""
        mock_client = mock_anthropic.return_value

        mock_batch = MagicMock()
        mock_batch.processing_status = "ended"
        mock_batch.request_counts.succeeded = 0
        mock_batch.request_counts.errored = 1
        mock_client.messages.batches.retrieve.return_value = mock_batch

        mock_result = MagicMock()
        mock_result.custom_id = "triage-0-RuntimeError"
        mock_result.result.type = "errored"
        mock_client.messages.batches.results.return_value = [mock_result]

        state = {
            "batch_id": "batch_err",
            "submitted_at": "2025-01-01T00:00:00",
            "error_count": 1,
            "custom_id_map": {
                "triage-0-RuntimeError": {
                    "error_class": "RuntimeError",
                    "transaction": "Controller/api/data",
                    "index": 0,
                }
            },
        }
        state_file = tmp_path / "batch_err.json"
        state_file.write_text(json.dumps(state))

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            results = analyzer.poll_results("batch_err", poll_interval=0)

        assert len(results) == 1
        assert results[0].needs_deep_investigation is True

    def test_poll_results_timeout_returns_empty(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """poll_results returns empty list when batch does not complete in time."""
        mock_client = mock_anthropic.return_value

        mock_batch = MagicMock()
        mock_batch.processing_status = "in_progress"
        mock_batch.request_counts.succeeded = 0
        mock_batch.request_counts.errored = 0
        mock_client.messages.batches.retrieve.return_value = mock_batch

        state = {
            "batch_id": "batch_timeout",
            "submitted_at": "2025-01-01T00:00:00",
            "error_count": 1,
            "custom_id_map": {},
        }
        state_file = tmp_path / "batch_timeout.json"
        state_file.write_text(json.dumps(state))

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            with patch("nightwatch.batch.time.sleep"):
                analyzer = BatchAnalyzer()
                results = analyzer.poll_results(
                    "batch_timeout", poll_interval=1, max_wait=2
                )

        assert results == []

    def test_poll_results_missing_state_raises(
        self, mock_settings, mock_anthropic, tmp_path
    ):
        """poll_results raises FileNotFoundError when no state file exists."""
        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            analyzer = BatchAnalyzer()
            with pytest.raises(FileNotFoundError, match="No saved state"):
                analyzer.poll_results("nonexistent_batch")


class TestParseTriage:
    def test_parse_valid_json(self, mock_settings, mock_anthropic):
        """_parse_triage handles clean JSON response."""
        analyzer = BatchAnalyzer()
        message = MagicMock()
        text_block = MagicMock()
        text_block.text = '{"severity": "low", "likely_root_cause": "test", "needs_deep_investigation": false, "fix_category": "config"}'
        message.content = [text_block]

        result = analyzer._parse_triage(message)
        assert result["severity"] == "low"
        assert result["needs_deep_investigation"] is False

    def test_parse_markdown_wrapped_json(self, mock_settings, mock_anthropic):
        """_parse_triage extracts JSON from markdown code blocks."""
        analyzer = BatchAnalyzer()
        message = MagicMock()
        text_block = MagicMock()
        text_block.text = '```json\n{"severity": "high", "likely_root_cause": "test", "needs_deep_investigation": true, "fix_category": "code_bug"}\n```'
        message.content = [text_block]

        result = analyzer._parse_triage(message)
        assert result["severity"] == "high"
        assert result["needs_deep_investigation"] is True

    def test_parse_invalid_json_returns_empty(
        self, mock_settings, mock_anthropic
    ):
        """_parse_triage returns empty dict for unparseable responses."""
        analyzer = BatchAnalyzer()
        message = MagicMock()
        text_block = MagicMock()
        text_block.text = "This is not JSON at all, just text."
        message.content = [text_block]

        result = analyzer._parse_triage(message)
        assert result == {}


class TestGetLatestBatchId:
    def test_returns_latest(self, tmp_path, mock_settings, mock_anthropic):
        """get_latest_batch_id returns the most recently modified batch."""
        import time as time_mod

        f1 = tmp_path / "batch_old.json"
        f1.write_text(json.dumps({"batch_id": "batch_old"}))
        time_mod.sleep(0.05)
        f2 = tmp_path / "batch_new.json"
        f2.write_text(json.dumps({"batch_id": "batch_new"}))

        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            result = BatchAnalyzer.get_latest_batch_id()
        assert result == "batch_new"

    def test_returns_none_when_empty(self, tmp_path):
        """get_latest_batch_id returns None when no state files exist."""
        with patch("nightwatch.batch.BATCH_STATE_DIR", tmp_path):
            result = BatchAnalyzer.get_latest_batch_id()
        assert result is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        """get_latest_batch_id returns None when batches dir does not exist."""
        missing = tmp_path / "nonexistent"
        with patch("nightwatch.batch.BATCH_STATE_DIR", missing):
            result = BatchAnalyzer.get_latest_batch_id()
        assert result is None


class TestCliArgs:
    def test_batch_flag(self):
        """--batch flag is parsed correctly."""
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch(
                "sys.argv", ["nightwatch", "run", "--batch", "--dry-run"]
            ):
                from nightwatch.__main__ import main

                result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.batch is True

    def test_collect_flag(self):
        """--collect flag is parsed correctly."""
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch", "run", "--collect"]):
                from nightwatch.__main__ import main

                result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.collect is True

    def test_batch_id_flag(self):
        """--batch-id flag is parsed correctly."""
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch(
                "sys.argv",
                [
                    "nightwatch",
                    "run",
                    "--collect",
                    "--batch-id",
                    "batch_abc123",
                ],
            ):
                from nightwatch.__main__ import main

                result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.batch_id == "batch_abc123"

    def test_default_args_include_batch_flags(self):
        """Default args (no subcommand) include batch-related defaults."""
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch"]):
                from nightwatch.__main__ import main

                result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.batch is False
        assert args.collect is False
        assert args.batch_id is None
