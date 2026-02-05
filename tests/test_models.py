"""Tests for NightWatch data models."""

from nightwatch.models import (
    Analysis,
    Confidence,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    RunReport,
    TraceData,
)


def test_confidence_enum():
    assert Confidence.HIGH == "high"
    assert Confidence.MEDIUM == "medium"
    assert Confidence.LOW == "low"


def test_file_change_defaults():
    fc = FileChange(path="app/models/user.rb", action="modify")
    assert fc.content is None
    assert fc.description == ""


def test_analysis_model():
    a = Analysis(
        title="NoMethodError in products/show",
        reasoning="Method called on nil",
        root_cause="Missing nil check",
        has_fix=True,
        confidence=Confidence.HIGH,
        file_changes=[FileChange(path="app/controllers/products_controller.rb", action="modify")],
        suggested_next_steps=["Add nil guard"],
    )
    assert a.has_fix is True
    assert len(a.file_changes) == 1
    assert a.confidence == "high"


def test_error_group_defaults():
    eg = ErrorGroup(
        error_class="NoMethodError",
        transaction="Controller/products/show",
        message="undefined method `name' for nil:NilClass",
        occurrences=42,
        last_seen="1707100000000",
    )
    assert eg.score == 0.0
    assert eg.http_path == ""
    assert eg.entity_guid is None


def test_run_report_properties():
    analysis_with_fix = ErrorAnalysisResult(
        error=ErrorGroup(
            error_class="NoMethodError",
            transaction="Controller/products/show",
            message="nil",
            occurrences=10,
            last_seen="",
        ),
        analysis=Analysis(
            title="Fix",
            reasoning="r",
            root_cause="rc",
            has_fix=True,
            confidence=Confidence.HIGH,
        ),
        traces=TraceData(),
    )
    analysis_no_fix = ErrorAnalysisResult(
        error=ErrorGroup(
            error_class="RuntimeError",
            transaction="Controller/users/index",
            message="err",
            occurrences=5,
            last_seen="",
        ),
        analysis=Analysis(
            title="Investigate",
            reasoning="r",
            root_cause="rc",
            has_fix=False,
            confidence=Confidence.LOW,
        ),
        traces=TraceData(),
    )

    report = RunReport(
        timestamp="2026-02-05T00:00:00Z",
        lookback="24h",
        total_errors_found=20,
        errors_filtered=5,
        errors_analyzed=2,
        analyses=[analysis_with_fix, analysis_no_fix],
    )

    assert report.fixes_found == 1
    assert report.high_confidence == 1
