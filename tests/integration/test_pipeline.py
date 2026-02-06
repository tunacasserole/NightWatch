"""Integration test for nightwatch.runner — full pipeline with all external APIs mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nightwatch.models import Analysis, Confidence, ErrorAnalysisResult, FileChange, TraceData
from nightwatch.runner import _best_fix_candidate, _confidence_float, _print_dry_run_summary
from tests.factories import (
    make_analysis,
    make_created_issue_result,
    make_error_analysis_result,
    make_error_group,
    make_run_report,
)


class TestConfidenceFloat:
    def test_high(self):
        assert _confidence_float("high") == 0.9

    def test_medium(self):
        assert _confidence_float("medium") == 0.6

    def test_low(self):
        assert _confidence_float("low") == 0.2

    def test_unknown(self):
        assert _confidence_float("unknown") == 0.0

    def test_confidence_enum(self):
        assert _confidence_float(Confidence.HIGH) == 0.9


class TestBestFixCandidate:
    def test_returns_high_confidence_with_fix(self):
        result = make_error_analysis_result(
            analysis=make_analysis(
                has_fix=True,
                confidence=Confidence.HIGH,
                file_changes=[FileChange(path="f.rb", action="modify", content="x")],
            ),
        )
        issue = make_created_issue_result(
            error=result.error,
            action="created",
            issue_number=42,
        )
        best = _best_fix_candidate([result], [issue])
        assert best is not None
        assert best[1] == 42

    def test_returns_none_when_no_fix(self):
        result = make_error_analysis_result(
            analysis=make_analysis(has_fix=False),
        )
        issue = make_created_issue_result(error=result.error, action="created", issue_number=42)
        assert _best_fix_candidate([result], [issue]) is None

    def test_returns_none_when_no_file_changes(self):
        result = make_error_analysis_result(
            analysis=make_analysis(has_fix=True, file_changes=[]),
        )
        issue = make_created_issue_result(error=result.error, action="created", issue_number=42)
        assert _best_fix_candidate([result], [issue]) is None

    def test_returns_none_when_no_matching_issue(self):
        result = make_error_analysis_result(
            analysis=make_analysis(
                has_fix=True,
                file_changes=[FileChange(path="f.rb", action="modify", content="x")],
            ),
        )
        # Issue has a different error
        issue = make_created_issue_result(
            error=make_error_group(error_class="DifferentError"),
            action="created",
            issue_number=42,
        )
        assert _best_fix_candidate([result], [issue]) is None

    def test_prefers_high_confidence(self):
        error1 = make_error_group(error_class="Error1", transaction="tx1")
        error2 = make_error_group(error_class="Error2", transaction="tx2")

        result_medium = make_error_analysis_result(
            error=error1,
            analysis=make_analysis(
                has_fix=True,
                confidence=Confidence.MEDIUM,
                file_changes=[FileChange(path="f.rb", action="modify", content="x")],
            ),
        )
        result_high = make_error_analysis_result(
            error=error2,
            analysis=make_analysis(
                has_fix=True,
                confidence=Confidence.HIGH,
                file_changes=[FileChange(path="g.rb", action="modify", content="y")],
            ),
        )
        issues = [
            make_created_issue_result(error=error1, action="created", issue_number=1),
            make_created_issue_result(error=error2, action="created", issue_number=2),
        ]
        best = _best_fix_candidate([result_medium, result_high], issues)
        assert best is not None
        assert best[1] == 2  # high confidence one

    def test_ignores_commented_issues(self):
        result = make_error_analysis_result(
            analysis=make_analysis(
                has_fix=True,
                file_changes=[FileChange(path="f.rb", action="modify", content="x")],
            ),
        )
        # Only "commented" issues, no "created" ones
        issue = make_created_issue_result(
            error=result.error,
            action="commented",
            issue_number=42,
        )
        assert _best_fix_candidate([result], [issue]) is None


class TestPrintDryRunSummary:
    def test_prints_summary(self, capsys):
        report = make_run_report(
            total_errors_found=20,
            errors_filtered=5,
            errors_analyzed=5,
            total_tokens_used=15000,
            total_api_calls=30,
            run_duration_seconds=60.0,
            multi_pass_retries=1,
        )
        _print_dry_run_summary(report)
        captured = capsys.readouterr()
        assert "Dry Run Summary" in captured.out
        assert "20" in captured.out
        assert "15,000" in captured.out
        assert "Multi-pass" in captured.out


class TestRunPipelineDryRun:
    """Integration test: run the full pipeline in dry-run mode with all APIs mocked."""

    @patch("nightwatch.runner.NewRelicClient")
    @patch("nightwatch.runner.GitHubClient")
    @patch("nightwatch.observability.configure_opik", return_value=False)
    @patch("nightwatch.runner.analyze_error")
    @patch("nightwatch.runner.search_prior_knowledge")
    @patch("nightwatch.runner.research_error")
    @patch("nightwatch.runner.fetch_recent_merged_prs")
    @patch("nightwatch.runner.load_ignore_patterns")
    @patch("nightwatch.runner.detect_patterns_with_knowledge")
    @patch("nightwatch.runner.suggest_ignore_updates")
    def test_dry_run_pipeline(
        self,
        mock_suggest_ignore,
        mock_detect_patterns,
        mock_load_ignore,
        mock_fetch_prs,
        mock_research,
        mock_search_prior,
        mock_analyze,
        mock_configure_opik,
        mock_gh_cls,
        mock_nr_cls,
    ):
        from nightwatch.runner import run

        # NR returns 2 errors
        mock_nr = mock_nr_cls.return_value
        mock_nr.fetch_errors.return_value = [
            make_error_group(error_class="NoMethodError", occurrences=50),
            make_error_group(error_class="TypeError", occurrences=10),
        ]
        mock_nr.fetch_traces.return_value = TraceData()

        # GH mock
        mock_gh = mock_gh_cls.return_value
        mock_gh.repo = MagicMock()

        # No ignore patterns
        mock_load_ignore.return_value = []

        # No prior knowledge
        mock_search_prior.return_value = []

        # No research context
        mock_research.return_value = MagicMock(likely_files=[], file_previews={})

        # No correlated PRs
        mock_fetch_prs.return_value = []

        # Analyze returns results
        mock_analyze.return_value = make_error_analysis_result()

        # No patterns
        mock_detect_patterns.return_value = []
        mock_suggest_ignore.return_value = []

        report = run(dry_run=True, max_errors=2)

        assert report.errors_analyzed == 2
        assert report.total_errors_found == 2
        mock_analyze.assert_called()
        mock_nr.close.assert_called_once()
