"""Tests for quality gate evaluation in nightwatch.analyzer."""

from __future__ import annotations

from nightwatch.analyzer import _evaluate_analysis_quality
from nightwatch.models import (
    Analysis,
    ErrorAnalysisResult,
    ErrorGroup,
    TraceData,
)


def _make_result(
    confidence: str = "low",
    root_cause: str = "",
    has_fix: bool = False,
    file_changes: list | None = None,
    reasoning: str = "",
    next_steps: list | None = None,
) -> ErrorAnalysisResult:
    """Helper to create ErrorAnalysisResult with specified analysis."""

    return ErrorAnalysisResult(
        error=ErrorGroup(
            error_class="TestError",
            transaction="test/action",
            message="test",
            occurrences=1,
            last_seen="2026-01-01",
        ),
        analysis=Analysis(
            title="Test",
            reasoning=reasoning,
            root_cause=root_cause,
            has_fix=has_fix,
            confidence=confidence,
            file_changes=file_changes or [],
            suggested_next_steps=next_steps or [],
        ),
        traces=TraceData(),
    )


def test_quality_score_low_confidence_no_details():
    """Low confidence + no details = low quality score."""
    result = _make_result(confidence="low")
    score = _evaluate_analysis_quality(result)
    assert score < 0.2


def test_quality_score_high_confidence_full_analysis():
    """High confidence with full analysis = high quality score."""
    from nightwatch.models import FileChange

    result = _make_result(
        confidence="high",
        root_cause="The API call to external service lacks timeout config, causing exhaustion",
        has_fix=True,
        file_changes=[
            FileChange(path="app/services/api.rb", action="modify", description="Add timeout")
        ],
        reasoning="Investigation of the error traces shows repeated timeout patterns..." * 5,
        next_steps=["Add circuit breaker", "Add monitoring alerts"],
    )
    score = _evaluate_analysis_quality(result)
    assert score >= 0.8


def test_quality_score_medium_confidence_partial():
    """Medium confidence with some details = mid-range score."""
    result = _make_result(
        confidence="medium",
        root_cause="Possible nil reference in user controller",
        reasoning="The error occurs when user is not found." * 3,
        next_steps=["Check nil handling"],
    )
    score = _evaluate_analysis_quality(result)
    assert 0.3 <= score <= 0.7


def test_quality_score_caps_at_one():
    """Quality score never exceeds 1.0."""
    from nightwatch.models import FileChange

    result = _make_result(
        confidence="high",
        root_cause="A very long and detailed root cause " * 20,
        has_fix=True,
        file_changes=[
            FileChange(path="a.rb", action="modify", description="d"),
            FileChange(path="b.rb", action="modify", description="d"),
        ],
        reasoning="Extremely detailed reasoning " * 50,
        next_steps=["Step 1", "Step 2", "Step 3", "Step 4"],
    )
    score = _evaluate_analysis_quality(result)
    assert score <= 1.0


def test_quality_score_has_fix_without_files():
    """has_fix=True but no file_changes gets partial credit."""
    result = _make_result(
        confidence="medium",
        root_cause="Known issue with timeout handling",
        has_fix=True,
        file_changes=[],  # No actual file changes
    )
    score = _evaluate_analysis_quality(result)
    # Should get partial fix credit (0.10) not full (0.20)
    score_no_fix = _evaluate_analysis_quality(
        _make_result(
            confidence="medium",
            root_cause="Known issue with timeout handling",
            has_fix=False,
        )
    )
    assert score > score_no_fix


def test_quality_score_short_root_cause():
    """Very short root cause gets less credit."""
    short = _evaluate_analysis_quality(
        _make_result(confidence="low", root_cause="Bug")
    )
    long = _evaluate_analysis_quality(
        _make_result(
            confidence="low",
            root_cause="The error is caused by a missing nil check in the user lookup method",
        )
    )
    assert long > short


def test_quality_score_unknown_root_cause():
    """'Unknown' root cause gets no credit."""
    result = _make_result(confidence="low", root_cause="Unknown")
    score = _evaluate_analysis_quality(result)
    assert score < 0.15
