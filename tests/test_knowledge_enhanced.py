"""Tests for enhanced knowledge.py functions (build_knowledge_context, save_error_pattern)."""

from __future__ import annotations

from unittest.mock import patch

from nightwatch.knowledge import (
    _parse_frontmatter,
    build_knowledge_context,
    save_error_pattern,
)
from nightwatch.models import ErrorGroup, PriorAnalysis


def _make_error(error_class: str = "TestError", transaction: str = "test/action") -> ErrorGroup:
    return ErrorGroup(
        error_class=error_class,
        transaction=transaction,
        message="test message",
        occurrences=5,
        last_seen="2026-01-01",
    )


def test_build_knowledge_context_no_prior():
    """Returns empty string when no prior knowledge found."""
    with patch("nightwatch.knowledge.search_prior_knowledge", return_value=[]):
        result = build_knowledge_context(_make_error())
    assert result == ""


def test_build_knowledge_context_with_priors():
    """Returns formatted context with prior analyses."""
    priors = [
        PriorAnalysis(
            error_class="TestError",
            transaction="test/action",
            root_cause="Missing nil check in user lookup",
            fix_confidence="high",
            has_fix=True,
            summary="Added safe navigation operator",
            match_score=0.8,
            source_file="test.md",
            first_detected="2026-01-01",
        ),
    ]
    with patch("nightwatch.knowledge.search_prior_knowledge", return_value=priors):
        result = build_knowledge_context(_make_error())

    assert "Prior Knowledge" in result
    assert "TestError" in result
    assert "Missing nil check" in result
    assert "80" in result  # 0.8 = 80%


def test_build_knowledge_context_truncates():
    """Context is truncated to max_chars."""
    priors = [
        PriorAnalysis(
            error_class="TestError",
            transaction="test/action",
            root_cause="A" * 500,
            fix_confidence="high",
            has_fix=True,
            summary="B" * 500,
            match_score=0.9,
            source_file="test.md",
            first_detected="2026-01-01",
        ),
    ]
    with patch("nightwatch.knowledge.search_prior_knowledge", return_value=priors):
        result = build_knowledge_context(_make_error(), max_chars=200)

    assert len(result) <= 200
    assert "truncated" in result


def test_save_error_pattern_creates_file(tmp_path):
    """save_error_pattern creates a markdown file with frontmatter."""
    settings_mock = type("Settings", (), {"nightwatch_knowledge_dir": str(tmp_path)})()
    with patch("nightwatch.knowledge.get_settings", return_value=settings_mock):
        result = save_error_pattern(
            error_class="Net::ReadTimeout",
            transaction="Controller/products/show",
            pattern_description="External API lacks timeout configuration",
            confidence="high",
        )

    assert result is not None
    assert result.exists()
    content = result.read_text()
    frontmatter, body = _parse_frontmatter(content)
    assert frontmatter["error_classes"] == ["Net::ReadTimeout"]
    assert frontmatter["pattern_type"] == "recurring_error"
    assert frontmatter["confidence"] == "high"
    assert "External API lacks timeout" in body


def test_save_error_pattern_creates_patterns_dir(tmp_path):
    """save_error_pattern creates patterns/ subdirectory."""
    kb_dir = tmp_path / "knowledge"
    settings_mock = type("Settings", (), {"nightwatch_knowledge_dir": str(kb_dir)})()
    with patch("nightwatch.knowledge.get_settings", return_value=settings_mock):
        save_error_pattern(
            error_class="TestError",
            transaction="test",
            pattern_description="test pattern",
        )

    assert (kb_dir / "patterns").exists()


def test_save_error_pattern_returns_none_on_error(tmp_path):
    """save_error_pattern returns None when write fails."""
    # Use a path that can't be written to
    settings_mock = type("Settings", (), {"nightwatch_knowledge_dir": "/dev/null/impossible"})()
    with patch("nightwatch.knowledge.get_settings", return_value=settings_mock):
        result = save_error_pattern(
            error_class="TestError",
            transaction="test",
            pattern_description="test",
        )
    assert result is None


def test_token_breakdown_model():
    """TokenBreakdown model computes totals and savings."""
    from nightwatch.models import TokenBreakdown

    tb = TokenBreakdown(
        input_tokens=5000,
        output_tokens=3000,
        thinking_tokens=2000,
        cache_read_tokens=1500,
        cache_write_tokens=500,
        tool_result_tokens=1000,
    )
    assert tb.total == 8000  # input + output
    assert tb.cache_savings == 1500

    d = tb.to_dict()
    assert d["total"] == 8000
    assert d["cache_savings"] == 1500
    assert d["thinking"] == 2000


def test_error_analysis_result_has_quality_score():
    """ErrorAnalysisResult includes quality_score field."""
    from nightwatch.models import Analysis, ErrorAnalysisResult, TraceData

    result = ErrorAnalysisResult(
        error=_make_error(),
        analysis=Analysis(
            title="Test",
            reasoning="test",
            root_cause="test",
            has_fix=False,
            confidence="low",
        ),
        traces=TraceData(),
        quality_score=0.75,
    )
    assert result.quality_score == 0.75


def test_error_analysis_result_has_token_breakdown():
    """ErrorAnalysisResult includes token_breakdown field."""
    from nightwatch.models import Analysis, ErrorAnalysisResult, TokenBreakdown, TraceData

    tb = TokenBreakdown(input_tokens=100, output_tokens=50)
    result = ErrorAnalysisResult(
        error=_make_error(),
        analysis=Analysis(
            title="Test",
            reasoning="test",
            root_cause="test",
            has_fix=False,
            confidence="low",
        ),
        traces=TraceData(),
        token_breakdown=tb,
    )
    assert result.token_breakdown is not None
    assert result.token_breakdown.total == 150
