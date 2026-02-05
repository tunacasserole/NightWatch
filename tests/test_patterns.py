"""Tests for cross-error pattern detection (patterns.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from nightwatch.models import (
    Analysis,
    DetectedPattern,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    TraceData,
)
from nightwatch.patterns import (
    TRANSIENT_INDICATORS,
    _detect_error_class_clusters,
    _detect_file_hotspots,
    _detect_module_clusters,
    _detect_transient_errors,
    _get_current_ignore_patterns,
    _is_transient_error,
    _transaction_to_directory,
    detect_patterns,
    detect_patterns_with_knowledge,
    suggest_ignore_updates,
    suggest_ignores,
    write_pattern_doc,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    error_class: str = "NoMethodError",
    transaction: str = "Controller/products/show",
    occurrences: int = 10,
    confidence: str = "high",
    has_fix: bool = True,
    file_changes: list[dict] | None = None,
    message: str = "undefined method",
) -> ErrorAnalysisResult:
    """Build an ErrorAnalysisResult with sensible defaults."""
    fc_list = []
    if file_changes:
        for fc in file_changes:
            fc_list.append(
                FileChange(
                    path=fc.get("path", "app/models/user.rb"),
                    action=fc.get("action", "modify"),
                    content=fc.get("content", "fix"),
                    description=fc.get("description", "fix it"),
                )
            )

    return ErrorAnalysisResult(
        error=ErrorGroup(
            error_class=error_class,
            transaction=transaction,
            message=message,
            occurrences=occurrences,
            last_seen="2026-02-05T00:00:00Z",
        ),
        analysis=Analysis(
            title=f"{error_class} in {transaction}",
            reasoning="test reasoning",
            root_cause="test root cause",
            has_fix=has_fix,
            confidence=confidence,
            file_changes=fc_list,
            suggested_next_steps=[],
        ),
        traces=TraceData(),
        iterations=3,
        tokens_used=5000,
        api_calls=3,
    )


# ---------------------------------------------------------------------------
# _transaction_to_directory
# ---------------------------------------------------------------------------


class TestTransactionToDirectory:
    def test_controller_transaction(self):
        assert _transaction_to_directory("Controller/orders/update") == "app/controllers/orders"

    def test_nested_controller(self):
        assert (
            _transaction_to_directory("Controller/api/v2/products/index")
            == "app/controllers/api/v2/products"
        )

    def test_non_controller_returns_empty(self):
        assert _transaction_to_directory("OtherTransaction/Rake/some_task") == ""

    def test_short_controller_returns_empty(self):
        assert _transaction_to_directory("Controller/") == ""

    def test_web_transaction_returns_empty(self):
        assert _transaction_to_directory("WebTransaction/Sinatra/GET /health") == ""


# ---------------------------------------------------------------------------
# detect_patterns — integration
# ---------------------------------------------------------------------------


class TestDetectPatterns:
    def test_too_few_analyses_returns_empty(self):
        """With only 1 analysis, no patterns can be detected (need min 2)."""
        results = detect_patterns([_make_result()])
        assert results == []

    def test_detects_module_cluster(self):
        """Two errors in the same directory should produce a module cluster pattern."""
        analyses = [
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/orders/show",
                file_changes=[{"path": "app/controllers/orders_controller.rb"}],
            ),
            _make_result(
                error_class="ActiveRecord::RecordNotFound",
                transaction="Controller/orders/update",
                file_changes=[{"path": "app/controllers/orders_controller.rb"}],
            ),
        ]
        patterns = detect_patterns(analyses)
        # Should detect module cluster in app/controllers
        module_patterns = [
            p for p in patterns
            if "app/controllers" in p.title
            or "app/controllers" in str(p.modules)
        ]
        assert len(module_patterns) > 0

    def test_detects_error_class_cluster(self):
        """Same error class across multiple transactions should be detected."""
        analyses = [
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/orders/show",
            ),
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/products/index",
            ),
        ]
        patterns = detect_patterns(analyses)
        recurring = [p for p in patterns if p.pattern_type == "recurring_error"]
        assert len(recurring) >= 1
        assert recurring[0].error_classes == ["NoMethodError"]

    def test_detects_file_hotspot(self):
        """File referenced by multiple analyses should be a hotspot."""
        analyses = [
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/orders/show",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
            _make_result(
                error_class="TypeError",
                transaction="Controller/products/index",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
        ]
        patterns = detect_patterns(analyses)
        hotspots = [
            p for p in patterns
            if p.pattern_type == "systemic_issue" and "Hotspot" in p.title
        ]
        assert len(hotspots) >= 1
        assert "user.rb" in hotspots[0].title

    def test_sorted_by_occurrences_desc(self):
        """Patterns should be sorted by occurrence count descending."""
        analyses = [
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/orders/show",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/products/index",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/cart/checkout",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
        ]
        patterns = detect_patterns(analyses)
        if len(patterns) > 1:
            assert patterns[0].occurrences >= patterns[1].occurrences


# ---------------------------------------------------------------------------
# _detect_error_class_clusters
# ---------------------------------------------------------------------------


class TestErrorClassClusters:
    def test_single_error_class_no_cluster(self):
        analyses = [_make_result(error_class="UniqueError")]
        assert _detect_error_class_clusters(analyses, min_size=2) == []

    def test_two_same_class_different_tx(self):
        analyses = [
            _make_result(error_class="NoMethodError", transaction="Controller/a/show"),
            _make_result(error_class="NoMethodError", transaction="Controller/b/index"),
        ]
        patterns = _detect_error_class_clusters(analyses, min_size=2)
        assert len(patterns) == 1
        assert patterns[0].error_classes == ["NoMethodError"]
        assert patterns[0].occurrences == 2


# ---------------------------------------------------------------------------
# _detect_file_hotspots
# ---------------------------------------------------------------------------


class TestFileHotspots:
    def test_no_file_changes_no_hotspots(self):
        analyses = [
            _make_result(file_changes=[]),
            _make_result(file_changes=[]),
        ]
        assert _detect_file_hotspots(analyses, min_size=2) == []

    def test_shared_file_produces_hotspot(self):
        analyses = [
            _make_result(file_changes=[{"path": "lib/shared.rb"}]),
            _make_result(file_changes=[{"path": "lib/shared.rb"}]),
        ]
        patterns = _detect_file_hotspots(analyses, min_size=2)
        assert len(patterns) == 1
        assert "lib/shared.rb" in patterns[0].title

    def test_different_files_no_hotspot(self):
        analyses = [
            _make_result(file_changes=[{"path": "lib/a.rb"}]),
            _make_result(file_changes=[{"path": "lib/b.rb"}]),
        ]
        assert _detect_file_hotspots(analyses, min_size=2) == []


# ---------------------------------------------------------------------------
# _detect_module_clusters
# ---------------------------------------------------------------------------


class TestModuleClusters:
    def test_two_errors_same_directory(self):
        analyses = [
            _make_result(
                transaction="Controller/orders/show",
                file_changes=[{"path": "app/controllers/orders_controller.rb"}],
            ),
            _make_result(
                transaction="Controller/orders/update",
                file_changes=[{"path": "app/controllers/orders_helper.rb"}],
            ),
        ]
        patterns = _detect_module_clusters(analyses, min_size=2)
        # Should detect cluster in app/controllers
        assert len(patterns) >= 1
        dirs = [d for p in patterns for d in p.modules]
        assert any("app/controllers" in d for d in dirs)

    def test_no_common_directory_no_cluster(self):
        analyses = [
            _make_result(
                transaction="Controller/orders/show",
                file_changes=[{"path": "app/models/user.rb"}],
            ),
            _make_result(
                transaction="Controller/products/index",
                file_changes=[{"path": "lib/services/payment.rb"}],
            ),
        ]
        patterns = _detect_module_clusters(analyses, min_size=2)
        # No single directory should have 2+ errors from file changes alone
        # (transactions map to different controllers)
        file_dirs = {"app/models", "lib/services"}
        for p in patterns:
            # Only module clusters from file-change dirs should not cluster
            for m in p.modules:
                if m in file_dirs:
                    assert p.occurrences < 2


# ---------------------------------------------------------------------------
# suggest_ignores
# ---------------------------------------------------------------------------


class TestSuggestIgnores:
    def test_low_confidence_no_fix_suggests_ignore(self):
        analyses = [
            _make_result(
                error_class="SomeTransientError",
                confidence="low",
                has_fix=False,
                occurrences=10,
            ),
        ]
        suggestions = suggest_ignores(analyses, min_occurrences=3)
        assert len(suggestions) >= 1
        assert suggestions[0].pattern == "SomeTransientError"

    def test_high_confidence_not_suggested(self):
        analyses = [
            _make_result(confidence="high", has_fix=True, occurrences=100),
        ]
        suggestions = suggest_ignores(analyses, min_occurrences=3)
        # High confidence with fix should NOT be suggested for ignore
        assert not any(s.pattern == "NoMethodError" for s in suggestions)

    def test_noise_pattern_detected(self):
        analyses = [
            _make_result(
                error_class="Net::ReadTimeout",
                message="execution expired (timeout)",
                confidence="medium",
                has_fix=False,
                occurrences=50,
            ),
        ]
        suggestions = suggest_ignores(analyses, min_occurrences=3)
        noise_suggestions = [s for s in suggestions if s.match == "contains"]
        assert len(noise_suggestions) >= 1
        assert "timeout" in noise_suggestions[0].pattern

    def test_low_occurrences_not_suggested(self):
        analyses = [
            _make_result(
                confidence="low",
                has_fix=False,
                occurrences=1,
            ),
        ]
        suggestions = suggest_ignores(analyses, min_occurrences=3)
        # Only 1 occurrence, below the threshold
        exact_suggestions = [s for s in suggestions if s.match == "exact"]
        assert len(exact_suggestions) == 0

    def test_deduplication(self):
        """Same error appearing twice should produce only one suggestion."""
        analyses = [
            _make_result(
                error_class="TimeoutError",
                message="timeout occurred",
                confidence="low",
                has_fix=False,
                occurrences=20,
            ),
            _make_result(
                error_class="TimeoutError",
                message="timeout occurred again",
                confidence="low",
                has_fix=False,
                occurrences=15,
            ),
        ]
        suggestions = suggest_ignores(analyses, min_occurrences=3)
        # Should deduplicate by pattern
        timeout_exact = [
            s for s in suggestions
            if s.pattern == "TimeoutError" and s.match == "exact"
        ]
        assert len(timeout_exact) == 1


# ---------------------------------------------------------------------------
# Knowledge-base integration tests (Phase 4)
# ---------------------------------------------------------------------------


class TestTransientErrorDetection:
    def test_timeout_is_transient(self):
        result = _make_result(
            error_class="Net::ReadTimeout",
            message="execution expired",
        )
        assert _is_transient_error(result)

    def test_rate_limit_is_transient(self):
        result = _make_result(
            error_class="ApiError",
            message="Rate limit exceeded",
        )
        assert _is_transient_error(result)

    def test_normal_error_not_transient(self):
        result = _make_result(
            error_class="NoMethodError",
            message="undefined method 'foo' for nil:NilClass",
        )
        assert not _is_transient_error(result)

    def test_detect_transient_patterns(self):
        analyses = [
            _make_result(
                error_class="Net::ReadTimeout",
                message="timeout occurred",
            ),
            _make_result(
                error_class="NoMethodError",
                message="undefined method",
            ),
        ]
        patterns = _detect_transient_errors(analyses)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "transient_noise"
        assert "Net::ReadTimeout" in patterns[0].error_classes

    def test_no_transient_errors(self):
        analyses = [
            _make_result(error_class="NoMethodError", message="undefined method"),
        ]
        patterns = _detect_transient_errors(analyses)
        assert patterns == []

    def test_transient_indicators_set(self):
        """TRANSIENT_INDICATORS should have known patterns."""
        assert "timeout" in TRANSIENT_INDICATORS
        assert "rate limit" in TRANSIENT_INDICATORS
        assert "deadlock" in TRANSIENT_INDICATORS


class TestDetectPatternsWithKnowledge:
    def test_includes_base_patterns(self):
        """Should include all base detect_patterns results."""
        analyses = [
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/orders/show",
            ),
            _make_result(
                error_class="NoMethodError",
                transaction="Controller/products/index",
            ),
        ]
        # Use a non-existent knowledge dir so no KB patterns
        patterns = detect_patterns_with_knowledge(
            analyses, knowledge_dir="/tmp/nonexistent_kb_dir"
        )
        recurring = [p for p in patterns if p.pattern_type == "recurring_error"]
        assert len(recurring) >= 1

    def test_finds_recurring_from_knowledge_base(self):
        """Should detect errors that match knowledge base entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir)
            index = {
                "solutions": [
                    {
                        "file": "errors/test.md",
                        "error_class": "NoMethodError",
                        "transaction": "Controller/products/show",
                        "fix_confidence": "high",
                        "has_fix": True,
                        "tags": [],
                    }
                ],
                "patterns": [],
            }
            (kb_dir / "index.yml").write_text(yaml.dump(index))

            analyses = [
                _make_result(error_class="NoMethodError"),
            ]
            patterns = detect_patterns_with_knowledge(
                analyses, knowledge_dir=str(kb_dir)
            )
            recurring_kb = [
                p for p in patterns
                if "Recurring" in p.title
            ]
            assert len(recurring_kb) >= 1


class TestWritePatternDoc:
    def test_writes_pattern_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pattern = DetectedPattern(
                title="Multiple errors in app/controllers",
                description="3 errors in app/controllers module.",
                error_classes=["NoMethodError", "TypeError"],
                modules=["app/controllers"],
                occurrences=3,
                suggestion="Review app/controllers for systemic issues.",
                pattern_type="systemic_issue",
            )
            path = write_pattern_doc(pattern, knowledge_dir=tmpdir)
            assert path.exists()
            content = path.read_text()
            assert "Multiple errors in app/controllers" in content
            assert "systemic_issue" in content

    def test_creates_patterns_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir) / "kb"
            pattern = DetectedPattern(
                title="Test pattern",
                description="Test",
                error_classes=["Err"],
                modules=[],
                occurrences=1,
                suggestion="Test",
                pattern_type="recurring_error",
            )
            path = write_pattern_doc(pattern, knowledge_dir=str(kb_dir))
            assert (kb_dir / "patterns").is_dir()
            assert path.exists()


class TestSuggestIgnoreUpdates:
    def test_filters_existing_patterns(self):
        """Should not suggest patterns already in ignore.yml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ignore_path = Path(tmpdir) / "ignore.yml"
            ignore_path.write_text(yaml.dump({
                "ignore": [
                    {"pattern": "timeout", "match": "contains"},
                ]
            }))

            analyses = [
                _make_result(
                    error_class="Net::ReadTimeout",
                    message="timeout exceeded",
                    confidence="low",
                    has_fix=False,
                    occurrences=20,
                ),
            ]
            suggestions = suggest_ignore_updates(
                analyses, ignore_path=str(ignore_path), min_occurrences=3
            )
            # "timeout" should be filtered out since it's already in ignore.yml
            timeout_suggestions = [
                s for s in suggestions
                if s.pattern == "timeout"
            ]
            assert len(timeout_suggestions) == 0

    def test_returns_new_patterns(self):
        """Should return patterns not in ignore.yml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ignore_path = Path(tmpdir) / "ignore.yml"
            ignore_path.write_text(yaml.dump({"ignore": []}))

            analyses = [
                _make_result(
                    error_class="SomeNewError",
                    confidence="low",
                    has_fix=False,
                    occurrences=10,
                ),
            ]
            suggestions = suggest_ignore_updates(
                analyses, ignore_path=str(ignore_path), min_occurrences=3
            )
            assert len(suggestions) >= 1


class TestGetCurrentIgnorePatterns:
    def test_loads_patterns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ignore.yml"
            path.write_text(yaml.dump({
                "ignore": [
                    {"pattern": "timeout", "match": "contains"},
                    {"pattern": "Net::ReadTimeout", "match": "exact"},
                ]
            }))
            patterns = _get_current_ignore_patterns(str(path))
            assert "timeout" in patterns
            assert "net::readtimeout" in patterns  # lowercased

    def test_missing_file_returns_empty(self):
        patterns = _get_current_ignore_patterns("/tmp/nonexistent_ignore.yml")
        assert patterns == set()

    def test_string_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ignore.yml"
            path.write_text(yaml.dump({
                "ignore": ["timeout", "ssl"]
            }))
            patterns = _get_current_ignore_patterns(str(path))
            assert "timeout" in patterns
            assert "ssl" in patterns
