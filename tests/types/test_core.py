"""Tests for nightwatch.types.core — enums and foundational structures."""

from __future__ import annotations

from nightwatch.types.core import (
    Confidence,
    ErrorGroup,
    MatchType,
    PatternType,
    RunContext,
)


class TestConfidenceEnum:
    def test_values(self):
        assert Confidence.HIGH == "high"
        assert Confidence.MEDIUM == "medium"
        assert Confidence.LOW == "low"

    def test_is_str(self):
        assert isinstance(Confidence.HIGH, str)


class TestPatternTypeEnum:
    def test_values(self):
        assert PatternType.RECURRING_ERROR == "recurring_error"
        assert PatternType.SYSTEMIC_ISSUE == "systemic_issue"
        assert PatternType.TRANSIENT_NOISE == "transient_noise"

    def test_is_str(self):
        assert isinstance(PatternType.RECURRING_ERROR, str)


class TestMatchTypeEnum:
    def test_values(self):
        assert MatchType.CONTAINS == "contains"
        assert MatchType.EXACT == "exact"
        assert MatchType.PREFIX == "prefix"


class TestErrorGroup:
    def test_defaults(self):
        eg = ErrorGroup(
            error_class="NoMethodError",
            transaction="Controller/products/show",
            message="undefined method",
            occurrences=42,
            last_seen="1707100000000",
        )
        assert eg.score == 0.0
        assert eg.http_path == ""
        assert eg.entity_guid is None
        assert eg.host == ""


class TestRunContext:
    def test_empty_defaults(self):
        ctx = RunContext()
        assert ctx.files_examined == {}
        assert ctx.patterns_discovered == []
        assert ctx.errors_analyzed == []

    def test_to_prompt_section_empty(self):
        ctx = RunContext()
        assert ctx.to_prompt_section() == ""

    def test_record_analysis_and_prompt(self):
        ctx = RunContext()
        ctx.record_analysis("NoMethodError", "Controller/show", "nil check missing")
        ctx.record_file("app/controllers/show.rb", "Products controller")
        section = ctx.to_prompt_section()
        assert "NoMethodError" in section
        assert "app/controllers/show.rb" in section

    def test_record_file_truncates_summary(self):
        ctx = RunContext()
        ctx.record_file("long.rb", "x" * 200)
        assert len(ctx.files_examined["long.rb"]) == 80
