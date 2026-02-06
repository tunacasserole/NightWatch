"""Tests for nightwatch.__main__ — CLI argument parsing, command dispatch, exit codes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nightwatch.__main__ import main


class TestCliArgParsing:
    def test_run_default_no_args(self):
        """No subcommand defaults to 'run'."""
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch"]):
                result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.command == "run"
        assert args.dry_run is False
        assert args.verbose is False
        assert args.since is None
        assert args.agent == "base-analyzer"

    def test_run_with_flags(self):
        with patch("nightwatch.__main__._run", return_value=0) as mock_run, patch(
            "sys.argv",
            ["nightwatch", "run", "--since", "12h", "--max-errors", "10", "--dry-run", "--verbose"],
        ):
            result = main()
        assert result == 0
        args = mock_run.call_args[0][0]
        assert args.since == "12h"
        assert args.max_errors == 10
        assert args.dry_run is True
        assert args.verbose is True

    def test_run_with_model(self):
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch", "run", "--model", "claude-opus-4-6"]):
                result = main()
        args = mock_run.call_args[0][0]
        assert args.model == "claude-opus-4-6"

    def test_run_with_agent(self):
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch", "run", "--agent", "deep-analyzer"]):
                result = main()
        args = mock_run.call_args[0][0]
        assert args.agent == "deep-analyzer"

    def test_run_with_workflows(self):
        with patch("nightwatch.__main__._run", return_value=0) as mock_run:
            with patch("sys.argv", ["nightwatch", "run", "--workflows", "errors,ci_doctor"]):
                result = main()
        args = mock_run.call_args[0][0]
        assert args.workflows == "errors,ci_doctor"

    def test_check_command(self):
        with patch("nightwatch.__main__._check", return_value=0) as mock_check:
            with patch("sys.argv", ["nightwatch", "check"]):
                result = main()
        assert result == 0
        mock_check.assert_called_once()


class TestRunCommand:
    def test_success(self):
        with patch("nightwatch.__main__.runner") as mock_runner_module:
            with patch("nightwatch.runner.run") as mock_run:
                mock_run.return_value = None
                with patch("sys.argv", ["nightwatch", "run", "--dry-run"]):
                    result = main()
        assert result == 0

    def test_keyboard_interrupt_returns_130(self):
        with patch("nightwatch.runner.run", side_effect=KeyboardInterrupt):
            with patch("sys.argv", ["nightwatch", "run"]):
                result = main()
        assert result == 130

    def test_fatal_error_returns_1(self):
        with patch("nightwatch.runner.run", side_effect=RuntimeError("boom")):
            with patch("sys.argv", ["nightwatch", "run"]):
                result = main()
        assert result == 1


class TestCheckCommand:
    def test_check_success(self):
        with patch("nightwatch.config.get_settings") as mock_settings, \
             patch("nightwatch.newrelic.NewRelicClient") as mock_nr, \
             patch("nightwatch.github.GitHubClient") as mock_gh, \
             patch("nightwatch.slack.SlackClient") as mock_slack, \
             patch("anthropic.Anthropic") as mock_anthropic:
            # Config OK
            mock_settings.return_value = MagicMock(
                slack_notify_user="test",
                anthropic_api_key="key",
                nightwatch_model="model",
            )
            # New Relic OK
            nr_instance = mock_nr.return_value
            nr_instance.query_nrql.return_value = [{"count": 5}]
            # GitHub OK
            gh_instance = mock_gh.return_value
            gh_instance.repo = MagicMock(full_name="org/repo", default_branch="main")
            # Slack OK
            slack_instance = mock_slack.return_value
            slack_instance._get_user_id.return_value = "U123"
            # Claude OK
            mock_anthropic.return_value.messages.create.return_value = MagicMock()

            with patch("sys.argv", ["nightwatch", "check"]):
                result = main()
            assert result == 0

    def test_check_config_failure_returns_1(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("sys.argv", ["nightwatch", "check"]):
            from nightwatch.config import get_settings
            get_settings.cache_clear()
            result = main()
        assert result == 1
