"""Builder functions for test data — avoids brittle, duplicated fixture dicts."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from nightwatch.models import (
    Analysis,
    Confidence,
    CorrelatedPR,
    CreatedIssueResult,
    CreatedPRResult,
    DetectedPattern,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    IgnoreSuggestion,
    RunReport,
    TraceData,
)


def make_error_group(**overrides) -> ErrorGroup:
    defaults = {
        "error_class": "NoMethodError",
        "transaction": "Controller/products/show",
        "message": "undefined method `name' for nil:NilClass",
        "occurrences": 42,
        "last_seen": str(int(time.time() * 1000)),
        "http_path": "/products/42",
        "entity_guid": "test-entity-guid",
        "host": "web-1",
        "score": 0.75,
    }
    defaults.update(overrides)
    return ErrorGroup(**defaults)


def make_analysis(**overrides) -> Analysis:
    defaults = {
        "title": "NoMethodError in products/show",
        "reasoning": "The error occurs because Product#name is called on a nil object.",
        "root_cause": "Missing nil check in ProductsController#show",
        "has_fix": True,
        "confidence": Confidence.HIGH,
        "file_changes": [],
        "suggested_next_steps": ["Add nil guard to controller"],
    }
    defaults.update(overrides)
    return Analysis(**defaults)


def make_file_change(**overrides) -> FileChange:
    defaults = {
        "path": "app/controllers/products_controller.rb",
        "action": "modify",
        "content": "# fixed content",
        "description": "Add nil guard",
    }
    defaults.update(overrides)
    return FileChange(**defaults)


def make_trace_data(**overrides) -> TraceData:
    defaults = {
        "transaction_errors": [
            {
                "error.class": "NoMethodError",
                "error.message": "undefined method `name' for nil",
                "transactionName": "Controller/products/show",
                "path": "/products/42",
                "host": "web-1",
            }
        ],
        "error_traces": [
            {
                "error.message": "undefined method `name' for nil",
                "error.stack_trace": (
                    "app/controllers/products_controller.rb:15:in `show'\n"
                    "app/models/product.rb:42:in `display_name'"
                ),
            }
        ],
    }
    defaults.update(overrides)
    return TraceData(**defaults)


def make_error_analysis_result(**overrides) -> ErrorAnalysisResult:
    defaults = {
        "error": make_error_group(),
        "analysis": make_analysis(),
        "traces": make_trace_data(),
        "iterations": 5,
        "tokens_used": 8000,
        "api_calls": 12,
    }
    defaults.update(overrides)
    return ErrorAnalysisResult(**defaults)


def make_created_issue_result(**overrides) -> CreatedIssueResult:
    defaults = {
        "error": make_error_group(),
        "analysis": make_analysis(),
        "action": "created",
        "issue_number": 100,
        "issue_url": "https://github.com/test-org/test-repo/issues/100",
    }
    defaults.update(overrides)
    return CreatedIssueResult(**defaults)


def make_created_pr_result(**overrides) -> CreatedPRResult:
    defaults = {
        "issue_number": 100,
        "pr_number": 200,
        "pr_url": "https://github.com/test-org/test-repo/pull/200",
        "branch_name": "nightwatch/fix-nomethoderror-20260205",
        "files_changed": 1,
    }
    defaults.update(overrides)
    return CreatedPRResult(**defaults)


def make_correlated_pr(**overrides) -> CorrelatedPR:
    defaults = {
        "number": 50,
        "title": "Refactor product display logic",
        "url": "https://github.com/test-org/test-repo/pull/50",
        "merged_at": datetime.now(UTC).isoformat(),
        "changed_files": [
            "app/controllers/products_controller.rb",
            "app/models/product.rb",
        ],
        "overlap_score": 0.5,
    }
    defaults.update(overrides)
    return CorrelatedPR(**defaults)


def make_detected_pattern(**overrides) -> DetectedPattern:
    defaults = {
        "title": "Recurring nil errors in product module",
        "description": "Multiple NoMethodError on nil across product controllers.",
        "error_classes": ["NoMethodError"],
        "modules": ["products"],
        "occurrences": 3,
        "suggestion": "Add null object pattern to Product model.",
        "pattern_type": "recurring_error",
    }
    defaults.update(overrides)
    return DetectedPattern(**defaults)


def make_ignore_suggestion(**overrides) -> IgnoreSuggestion:
    defaults = {
        "pattern": "ActionController::RoutingError",
        "match": "exact",
        "reason": "Bot traffic triggering 404s on non-existent routes",
        "evidence": "100% of occurrences are on /wp-admin paths",
    }
    defaults.update(overrides)
    return IgnoreSuggestion(**defaults)


def make_run_report(**overrides) -> RunReport:
    result = make_error_analysis_result()
    defaults = {
        "timestamp": datetime.now(UTC).isoformat(),
        "lookback": "24h",
        "total_errors_found": 10,
        "errors_filtered": 3,
        "errors_analyzed": 5,
        "analyses": [result],
        "total_tokens_used": 15000,
        "total_api_calls": 25,
        "run_duration_seconds": 120.5,
    }
    defaults.update(overrides)
    return RunReport(**defaults)


# ---------------------------------------------------------------------------
# Mock API response factories
# ---------------------------------------------------------------------------


def make_nrql_error_row(**overrides) -> dict:
    """A single row from a New Relic NRQL error query."""
    defaults = {
        "error_class": "NoMethodError",
        "transaction": "Controller/products/show",
        "error_message": "undefined method `name' for nil:NilClass",
        "occurrences": 42,
        "last_seen": str(int(time.time() * 1000)),
        "http_path": "/products/42",
        "entity_guid": "test-guid",
        "host": "web-1",
        "facet": ["NoMethodError", "Controller/products/show"],
    }
    defaults.update(overrides)
    return defaults


def make_graphql_response(results: list[dict]) -> dict:
    """Wrap NRQL results in the New Relic GraphQL response envelope."""
    return {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": results,
                    }
                }
            }
        }
    }
