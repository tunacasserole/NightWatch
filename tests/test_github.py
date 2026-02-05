"""Tests for GitHub helpers (title building, label building, issue selection)."""

from nightwatch.github import _build_issue_title, _build_labels
from nightwatch.models import Analysis, Confidence, ErrorAnalysisResult, ErrorGroup, TraceData
from nightwatch.runner import select_for_issues


def _make_error(**kwargs) -> ErrorGroup:
    defaults = {
        "error_class": "NoMethodError",
        "transaction": "Controller/products/show",
        "message": "undefined method `name' for nil:NilClass",
        "occurrences": 42,
        "last_seen": "",
    }
    defaults.update(kwargs)
    return ErrorGroup(**defaults)


def _make_analysis(**kwargs) -> Analysis:
    defaults = {
        "title": "NoMethodError in products/show",
        "reasoning": "Method called on nil",
        "root_cause": "Missing nil check",
        "has_fix": False,
        "confidence": Confidence.MEDIUM,
    }
    defaults.update(kwargs)
    return Analysis(**defaults)


class TestBuildIssueTitle:
    def test_full_info(self):
        error = _make_error()
        analysis = _make_analysis()
        title = _build_issue_title(error, analysis)
        assert "NoMethodError" in title
        assert "products/show" in title

    def test_no_message(self):
        error = _make_error(message="")
        analysis = _make_analysis()
        title = _build_issue_title(error, analysis)
        assert title == "NoMethodError in products/show"

    def test_long_message_truncated(self):
        error = _make_error(message="x" * 100)
        analysis = _make_analysis()
        title = _build_issue_title(error, analysis)
        assert len(title) < 150

    def test_fallback(self):
        error = _make_error(error_class="", transaction="", message="")
        analysis = _make_analysis(title="Custom Title")
        title = _build_issue_title(error, analysis)
        assert title == "Custom Title"


class TestBuildLabels:
    def test_has_fix(self):
        analysis = _make_analysis(has_fix=True, confidence=Confidence.HIGH)
        labels = _build_labels(analysis)
        assert "nightwatch" in labels
        assert "has-fix" in labels
        assert "confidence:high" in labels

    def test_needs_investigation(self):
        analysis = _make_analysis(has_fix=False, confidence=Confidence.LOW)
        labels = _build_labels(analysis)
        assert "needs-investigation" in labels
        assert "confidence:low" in labels


class TestSelectForIssues:
    def test_skips_low_confidence_no_fix(self):
        results = [
            ErrorAnalysisResult(
                error=_make_error(),
                analysis=_make_analysis(has_fix=False, confidence=Confidence.LOW),
                traces=TraceData(),
            ),
        ]
        selected = select_for_issues(results, max_issues=3)
        assert len(selected) == 0

    def test_includes_high_confidence_fix(self):
        results = [
            ErrorAnalysisResult(
                error=_make_error(),
                analysis=_make_analysis(has_fix=True, confidence=Confidence.HIGH),
                traces=TraceData(),
            ),
        ]
        selected = select_for_issues(results, max_issues=3)
        assert len(selected) == 1

    def test_respects_max_issues(self):
        results = [
            ErrorAnalysisResult(
                error=_make_error(error_class=f"Error{i}"),
                analysis=_make_analysis(has_fix=True, confidence=Confidence.HIGH),
                traces=TraceData(),
            )
            for i in range(5)
        ]
        selected = select_for_issues(results, max_issues=2)
        assert len(selected) == 2

    def test_prioritizes_fixes_over_investigation(self):
        fix = ErrorAnalysisResult(
            error=_make_error(error_class="FixError"),
            analysis=_make_analysis(has_fix=True, confidence=Confidence.MEDIUM),
            traces=TraceData(),
        )
        investigate = ErrorAnalysisResult(
            error=_make_error(error_class="InvestError"),
            analysis=_make_analysis(has_fix=False, confidence=Confidence.MEDIUM),
            traces=TraceData(),
        )
        selected = select_for_issues([investigate, fix], max_issues=1)
        assert selected[0].error.error_class == "FixError"
