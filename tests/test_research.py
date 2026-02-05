"""Tests for pre-analysis research module (research.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nightwatch.models import CorrelatedPR, ErrorGroup, PriorAnalysis, TraceData
from nightwatch.research import (
    ResearchContext,
    _camel_to_snake,
    _infer_files_from_traces,
    _infer_files_from_transaction,
    _pre_fetch_files,
    research_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_error(
    error_class: str = "NoMethodError",
    transaction: str = "Controller/products/show",
    message: str = "undefined method 'foo'",
) -> ErrorGroup:
    return ErrorGroup(
        error_class=error_class,
        transaction=transaction,
        message=message,
        occurrences=10,
        last_seen="2026-02-05T00:00:00Z",
    )


def _make_traces(**kwargs) -> TraceData:
    return TraceData(**kwargs)


# ---------------------------------------------------------------------------
# _infer_files_from_transaction
# ---------------------------------------------------------------------------


class TestInferFilesFromTransaction:
    def test_simple_controller(self):
        files = _infer_files_from_transaction("Controller/products/show")
        assert "app/controllers/products_controller.rb" in files
        assert "app/models/product.rb" in files

    def test_namespaced_controller(self):
        files = _infer_files_from_transaction("Controller/api/v3/reviews/create")
        assert "app/controllers/api/v3/reviews_controller.rb" in files
        assert "app/models/review.rb" in files

    def test_sidekiq_job(self):
        files = _infer_files_from_transaction("Sidekiq/ImportJob")
        assert "app/jobs/import_job.rb" in files

    def test_other_transaction_returns_empty(self):
        files = _infer_files_from_transaction("OtherTransaction/Rake/db_migrate")
        assert files == []

    def test_rake_returns_empty(self):
        files = _infer_files_from_transaction("Rake/some_task")
        assert files == []

    def test_empty_string(self):
        files = _infer_files_from_transaction("")
        assert files == []


# ---------------------------------------------------------------------------
# _infer_files_from_traces
# ---------------------------------------------------------------------------


class TestInferFilesFromTraces:
    def test_extracts_app_paths(self):
        traces = _make_traces(
            error_traces=[
                {"error.stack_trace": (
                    "app/controllers/products_controller.rb:42:in `show'\n"
                    "app/models/product.rb:15:in `find_by_slug'\n"
                    "/usr/local/bundle/gems/activerecord-7.0/query.rb:99:in `find'"
                )},
            ]
        )
        files = _infer_files_from_traces(traces)
        assert "app/controllers/products_controller.rb" in files
        assert "app/models/product.rb" in files

    def test_lib_paths_included(self):
        traces = _make_traces(
            error_traces=[
                {"error.stack_trace": "lib/services/payment.rb:10:in `charge'"},
            ]
        )
        files = _infer_files_from_traces(traces)
        assert "lib/services/payment.rb" in files

    def test_empty_traces(self):
        traces = _make_traces(error_traces=[])
        files = _infer_files_from_traces(traces)
        assert files == []

    def test_max_five_files(self):
        # Build a trace with many file references
        lines = "\n".join(
            f"app/models/model_{i}.rb:1:in `foo'" for i in range(20)
        )
        traces = _make_traces(
            error_traces=[{"error.stack_trace": lines}]
        )
        files = _infer_files_from_traces(traces)
        assert len(files) <= 5

    def test_deduplication(self):
        traces = _make_traces(
            error_traces=[
                {"error.stack_trace": (
                    "app/models/user.rb:10\napp/models/user.rb:20"
                )},
            ]
        )
        files = _infer_files_from_traces(traces)
        assert files.count("app/models/user.rb") == 1


# ---------------------------------------------------------------------------
# _pre_fetch_files
# ---------------------------------------------------------------------------


class TestPreFetchFiles:
    def test_fetches_files(self):
        gh = MagicMock()
        gh.read_file.return_value = "class Product\nend"
        result = _pre_fetch_files(["app/models/product.rb"], gh)
        assert "app/models/product.rb" in result
        gh.read_file.assert_called_once_with("app/models/product.rb")

    def test_truncates_long_files(self):
        gh = MagicMock()
        long_content = "\n".join(f"line {i}" for i in range(200))
        gh.read_file.return_value = long_content
        result = _pre_fetch_files(["app/models/product.rb"], gh, max_lines=50)
        lines = result["app/models/product.rb"].split("\n")
        assert len(lines) == 51  # 50 lines + "# ... truncated"
        assert "truncated" in lines[-1]

    def test_skips_missing_files(self):
        gh = MagicMock()
        gh.read_file.return_value = None
        result = _pre_fetch_files(["app/models/missing.rb"], gh)
        assert result == {}

    def test_caps_at_max_files(self):
        gh = MagicMock()
        gh.read_file.return_value = "content"
        files = [f"app/models/m{i}.rb" for i in range(20)]
        result = _pre_fetch_files(files, gh, max_files=3)
        assert len(result) <= 3
        assert gh.read_file.call_count == 3

    def test_handles_exception(self):
        gh = MagicMock()
        gh.read_file.side_effect = Exception("API error")
        result = _pre_fetch_files(["app/models/user.rb"], gh)
        assert result == {}


# ---------------------------------------------------------------------------
# _camel_to_snake
# ---------------------------------------------------------------------------


class TestCamelToSnake:
    def test_simple_camel(self):
        assert _camel_to_snake("ImportJob") == "import_job"

    def test_acronym(self):
        assert _camel_to_snake("HTMLParser") == "html_parser"

    def test_already_snake(self):
        assert _camel_to_snake("import_job") == "import_job"


# ---------------------------------------------------------------------------
# research_error (integration)
# ---------------------------------------------------------------------------


class TestResearchError:
    def test_returns_research_context(self):
        gh = MagicMock()
        gh.read_file.return_value = "class Product\nend"
        error = _make_error(transaction="Controller/products/show")
        traces = _make_traces(error_traces=[])

        ctx = research_error(error, traces, gh)
        assert isinstance(ctx, ResearchContext)
        assert "app/controllers/products_controller.rb" in ctx.likely_files

    def test_passes_through_prior_analyses(self):
        gh = MagicMock()
        gh.read_file.return_value = None
        error = _make_error()
        traces = _make_traces(error_traces=[])
        prior = [
            PriorAnalysis(
                error_class="NoMethodError",
                transaction="Controller/products/show",
                root_cause="nil guard missing",
                fix_confidence="high",
                has_fix=True,
                summary="test",
                match_score=0.8,
                source_file="kb/errors/test.md",
                first_detected="2026-02-01",
            )
        ]

        ctx = research_error(error, traces, gh, prior_analyses=prior)
        assert ctx.prior_analyses == prior

    def test_passes_through_correlated_prs(self):
        gh = MagicMock()
        gh.read_file.return_value = None
        error = _make_error()
        traces = _make_traces(error_traces=[])
        prs = [
            CorrelatedPR(
                number=42,
                title="Fix product loading",
                url="https://github.com/test/repo/pull/42",
                merged_at="2026-02-05T10:00:00Z",
                changed_files=["app/models/product.rb"],
            )
        ]

        ctx = research_error(error, traces, gh, correlated_prs=prs)
        assert ctx.correlated_prs == prs
