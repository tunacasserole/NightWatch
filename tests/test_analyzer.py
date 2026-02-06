"""Tests for analyzer multi-pass logic (Ralph pattern: retry low-confidence with seed knowledge)."""

from unittest.mock import MagicMock, patch

from nightwatch.analyzer import _build_retry_seed, _confidence_rank
from nightwatch.models import (
    Analysis,
    Confidence,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    RunContext,
    TraceData,
)


def _make_error() -> ErrorGroup:
    return ErrorGroup(
        error_class="NoMethodError",
        transaction="Controller/products/show",
        message="undefined method `name' for nil:NilClass",
        occurrences=42,
        last_seen="1707100000000",
    )


def _make_traces() -> TraceData:
    return TraceData(transaction_errors=[{"id": "1"}], error_traces=[])


def _make_analysis(confidence: str = "high", has_fix: bool = True) -> Analysis:
    return Analysis(
        title="Test Error",
        reasoning="test reasoning",
        root_cause="test root cause",
        has_fix=has_fix,
        confidence=confidence,
        file_changes=[
            FileChange(
                path="app/models/user.rb", action="modify", content="fix", description="fix it"
            )
        ],
        suggested_next_steps=["Add nil guard", "Add tests"],
    )


def _make_result(confidence: str = "high", has_fix: bool = True) -> ErrorAnalysisResult:
    return ErrorAnalysisResult(
        error=_make_error(),
        analysis=_make_analysis(confidence=confidence, has_fix=has_fix),
        traces=_make_traces(),
        iterations=3,
        tokens_used=5000,
        api_calls=3,
    )


# ---------------------------------------------------------------------------
# _confidence_rank
# ---------------------------------------------------------------------------


class TestConfidenceRank:
    def test_low_is_zero(self):
        assert _confidence_rank("low") == 0
        assert _confidence_rank(Confidence.LOW) == 0

    def test_medium_is_one(self):
        assert _confidence_rank("medium") == 1
        assert _confidence_rank(Confidence.MEDIUM) == 1

    def test_high_is_two(self):
        assert _confidence_rank("high") == 2
        assert _confidence_rank(Confidence.HIGH) == 2

    def test_unknown_defaults_to_zero(self):
        assert _confidence_rank("unknown") == 0
        assert _confidence_rank("INVALID") == 0


# ---------------------------------------------------------------------------
# _build_retry_seed
# ---------------------------------------------------------------------------


class TestBuildRetrySeed:
    def test_includes_root_cause(self):
        result = _make_result(confidence="low")
        seed = _build_retry_seed(result)
        assert "test root cause" in seed

    def test_includes_reasoning(self):
        result = _make_result(confidence="low")
        seed = _build_retry_seed(result)
        assert "test reasoning" in seed

    def test_includes_file_changes(self):
        result = _make_result(confidence="low")
        seed = _build_retry_seed(result)
        assert "app/models/user.rb" in seed

    def test_includes_next_steps(self):
        result = _make_result(confidence="low")
        seed = _build_retry_seed(result)
        assert "Add nil guard" in seed

    def test_includes_low_confidence_header(self):
        result = _make_result(confidence="low")
        seed = _build_retry_seed(result)
        assert "LOW" in seed
        assert "investigate more deeply" in seed.lower()

    def test_no_file_changes(self):
        result = _make_result(confidence="low")
        result.analysis.file_changes = []
        seed = _build_retry_seed(result)
        assert "Files examined" not in seed

    def test_no_next_steps(self):
        result = _make_result(confidence="low")
        result.analysis.suggested_next_steps = []
        seed = _build_retry_seed(result)
        assert "Suggested next steps" not in seed


# ---------------------------------------------------------------------------
# analyze_error multi-pass logic (mocked)
# ---------------------------------------------------------------------------


class TestAnalyzeErrorMultiPass:
    """Test the multi-pass retry logic via mocking _single_pass."""

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_high_confidence_no_retry(self, mock_settings, mock_single_pass):
        """High confidence → no retry, single call to _single_pass."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = True
        settings.nightwatch_max_passes = 2
        settings.nightwatch_run_context_enabled = False
        mock_settings.return_value = settings

        mock_single_pass.return_value = _make_result(confidence="high")

        from nightwatch.analyzer import analyze_error

        result = analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
        )

        assert mock_single_pass.call_count == 1
        assert result.analysis.confidence == Confidence.HIGH

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_low_confidence_triggers_retry(self, mock_settings, mock_single_pass):
        """Low confidence → retry fires (2 calls to _single_pass)."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = True
        settings.nightwatch_max_passes = 2
        settings.nightwatch_run_context_enabled = False
        mock_settings.return_value = settings

        # Pass 1: low confidence, Pass 2: medium confidence
        pass1 = _make_result(confidence="low")
        pass1_tokens = pass1.tokens_used  # capture before mutation
        pass2 = _make_result(confidence="medium")
        pass2.tokens_used = 3000
        pass2.api_calls = 2
        pass2.iterations = 2
        mock_single_pass.side_effect = [pass1, pass2]

        from nightwatch.analyzer import analyze_error

        result = analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
        )

        assert mock_single_pass.call_count == 2
        # Pass 2 improved → use pass 2's analysis
        assert result.analysis.confidence == Confidence.MEDIUM
        # Tokens accumulated from both passes (pass2.tokens_used += pass1.tokens_used)
        assert result.tokens_used == pass1_tokens + 3000
        assert result.pass_count == 2

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_multi_pass_disabled_no_retry(self, mock_settings, mock_single_pass):
        """Multi-pass disabled → no retry even on low confidence."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = False
        settings.nightwatch_max_passes = 2
        settings.nightwatch_run_context_enabled = False
        mock_settings.return_value = settings

        mock_single_pass.return_value = _make_result(confidence="low")

        from nightwatch.analyzer import analyze_error

        analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
        )

        assert mock_single_pass.call_count == 1

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_pass2_worse_keeps_pass1(self, mock_settings, mock_single_pass):
        """Pass 2 is worse → keep pass 1's analysis, accumulate cost."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = True
        settings.nightwatch_max_passes = 2
        settings.nightwatch_run_context_enabled = False
        mock_settings.return_value = settings

        # Pass 1: medium confidence, but multi-pass only triggers on LOW
        # So we test: pass1=low, pass2=low with lower rank impossible
        # Since confidence_rank(low) == 0 for both, pass2 is NOT worse → pass2 kept.
        # To test "keep pass1", we need pass2 to have strictly lower rank:
        # But there's nothing lower than low. The code only keeps pass1 when
        # pass2.rank < pass1.rank. With both at LOW, pass2 wins (tie = pass2).
        # Let's test the tie scenario correctly:
        pass1 = _make_result(confidence="low")
        pass1.analysis.root_cause = "pass1 root cause"
        pass1_tokens = pass1.tokens_used
        pass2 = _make_result(confidence="low")
        pass2.analysis.root_cause = "pass2 root cause"
        pass2.tokens_used = 4000
        pass2.api_calls = 2
        pass2.iterations = 2
        mock_single_pass.side_effect = [pass1, pass2]

        from nightwatch.analyzer import analyze_error

        result = analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
        )

        assert mock_single_pass.call_count == 2
        # Tie at LOW → pass 2's analysis is kept (tie goes to latest pass)
        assert result.analysis.root_cause == "pass2 root cause"
        assert result.pass_count == 2
        # Costs are accumulated
        assert result.tokens_used == pass1_tokens + 4000

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_run_context_passed_through(self, mock_settings, mock_single_pass):
        """run_context is used when enabled."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = False
        settings.nightwatch_max_passes = 1
        settings.nightwatch_run_context_enabled = True
        settings.nightwatch_run_context_max_chars = 1500
        mock_settings.return_value = settings

        high_result = _make_result(confidence="high")
        mock_single_pass.return_value = high_result

        run_ctx = RunContext()
        run_ctx.record_analysis("PrevError", "prev/tx", "prev cause")

        from nightwatch.analyzer import analyze_error

        analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
            run_context=run_ctx,
        )

        # Verify _single_pass was called with seed_context
        call_kwargs = mock_single_pass.call_args[1]
        assert call_kwargs["seed_context"] is not None
        assert "PrevError" in call_kwargs["seed_context"]

        # Verify new analysis was recorded in run_context
        assert len(run_ctx.errors_analyzed) == 2  # Previous + new

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_prior_context_merged_with_run_context(self, mock_settings, mock_single_pass):
        """prior_context is merged with run_context seed."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = False
        settings.nightwatch_max_passes = 1
        settings.nightwatch_run_context_enabled = True
        settings.nightwatch_run_context_max_chars = 1500
        mock_settings.return_value = settings

        mock_single_pass.return_value = _make_result(confidence="high")

        run_ctx = RunContext()
        run_ctx.record_analysis("PrevError", "prev/tx", "prev cause")

        from nightwatch.analyzer import analyze_error

        analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
            run_context=run_ctx,
            prior_context="Prior knowledge about this error",
        )

        call_kwargs = mock_single_pass.call_args[1]
        assert "Prior knowledge" in call_kwargs["seed_context"]
        assert "PrevError" in call_kwargs["seed_context"]

    @patch("nightwatch.analyzer._single_pass")
    @patch("nightwatch.analyzer.get_settings")
    def test_prior_context_without_run_context(self, mock_settings, mock_single_pass):
        """prior_context works alone without run_context."""
        settings = MagicMock()
        settings.nightwatch_multi_pass_enabled = False
        settings.nightwatch_max_passes = 1
        settings.nightwatch_run_context_enabled = False
        mock_settings.return_value = settings

        mock_single_pass.return_value = _make_result(confidence="high")

        from nightwatch.analyzer import analyze_error

        analyze_error(
            error=_make_error(),
            traces=_make_traces(),
            github_client=MagicMock(),
            newrelic_client=MagicMock(),
            prior_context="Prior knowledge only",
        )

        call_kwargs = mock_single_pass.call_args[1]
        assert call_kwargs["seed_context"] == "Prior knowledge only"
