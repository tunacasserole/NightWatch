"""Tests for nightwatch.workflows.patterns module."""

from __future__ import annotations

from unittest.mock import patch

from nightwatch.workflows.base import SafeOutput, WorkflowResult
from nightwatch.workflows.patterns import PatternAnalysisWorkflow


def _mock_history():
    """Create mock run history with recurring errors."""
    return [
        {
            "errors_analyzed": [
                {"error_class": "Net::ReadTimeout", "confidence": "medium"},
                {"error_class": "NoMethodError", "confidence": "high"},
            ]
        },
        {
            "errors_analyzed": [
                {"error_class": "Net::ReadTimeout", "confidence": "low"},
                {"error_class": "Net::ReadTimeout", "confidence": "medium"},
            ]
        },
        {
            "errors_analyzed": [
                {"error_class": "Net::ReadTimeout", "confidence": "high"},
                {"error_class": "NoMethodError", "confidence": "medium"},
            ]
        },
    ]


def test_patterns_registration():
    """PatternAnalysisWorkflow is properly registered."""
    wf = PatternAnalysisWorkflow()
    assert wf.name == "patterns"


def test_patterns_safe_outputs():
    """PatternAnalysisWorkflow can create issues and send Slack."""
    wf = PatternAnalysisWorkflow()
    assert SafeOutput.CREATE_ISSUE in wf.safe_outputs
    assert SafeOutput.SEND_SLACK in wf.safe_outputs
    assert SafeOutput.CREATE_PR not in wf.safe_outputs


def test_patterns_fetch_aggregates():
    """fetch() aggregates error classes from history."""
    wf = PatternAnalysisWorkflow()
    with patch("nightwatch.workflows.patterns.load_history", return_value=_mock_history()):
        items = wf.fetch()

    assert len(items) >= 1
    # Net::ReadTimeout appears 4 times
    timeout_item = next(i for i in items if "Net::ReadTimeout" in i.id)
    assert timeout_item.metadata["count"] == 4


def test_patterns_fetch_empty_history():
    """fetch() returns empty list for no history."""
    wf = PatternAnalysisWorkflow()
    with patch("nightwatch.workflows.patterns.load_history", return_value=[]):
        items = wf.fetch()
    assert items == []


def test_patterns_filter_min_occurrences():
    """filter() only keeps patterns with minimum occurrences."""
    wf = PatternAnalysisWorkflow()
    with patch("nightwatch.workflows.patterns.load_history", return_value=_mock_history()):
        items = wf.fetch()

    # Default min_occurrences is 3
    filtered = wf.filter(items, min_occurrences=3)
    # Net::ReadTimeout (4 occurrences) should pass, NoMethodError (2) should not
    assert all(i.metadata["count"] >= 3 for i in filtered)


def test_patterns_analyze_severity():
    """analyze() assigns severity based on occurrence count."""
    wf = PatternAnalysisWorkflow()
    from nightwatch.workflows.base import WorkflowItem

    items = [
        WorkflowItem(
            id="HighError",
            title="HighError (12 occurrences)",
            metadata={"count": 12, "error_class": "HighError"},
        ),
        WorkflowItem(
            id="MedError",
            title="MedError (4 occurrences)",
            metadata={"count": 4, "error_class": "MedError"},
        ),
    ]
    analyses = wf.analyze(items)
    assert len(analyses) == 2
    assert analyses[0].details["severity"] == "critical"  # 12 >= 10
    assert analyses[1].details["severity"] == "medium"  # 4 < 5


def test_patterns_act_creates_issues():
    """act() creates issue actions for high-confidence patterns."""
    wf = PatternAnalysisWorkflow()
    from nightwatch.workflows.base import WorkflowAnalysis, WorkflowItem

    analyses = [
        WorkflowAnalysis(
            item=WorkflowItem(
                id="Error",
                title="Error",
                metadata={"error_class": "TestError"},
            ),
            summary="Recurring TestError",
            confidence=0.8,
        )
    ]
    actions = wf.act(analyses, dry_run=True)
    assert len(actions) == 1
    assert actions[0].action_type == SafeOutput.CREATE_ISSUE


def test_patterns_report_section():
    """report_section generates Slack blocks."""
    wf = PatternAnalysisWorkflow()
    from nightwatch.workflows.base import WorkflowAnalysis, WorkflowItem

    result = WorkflowResult(
        workflow_name="patterns",
        analyses=[
            WorkflowAnalysis(
                item=WorkflowItem(id="E", title="E"),
                summary="Recurring E (5 times)",
                details={"severity": "high", "count": 5},
                confidence=0.85,
            )
        ],
    )
    blocks = wf.report_section(result)
    assert len(blocks) >= 1
    assert "Pattern Analysis" in blocks[0]["text"]["text"]


def test_patterns_report_section_empty():
    """report_section returns empty for no analyses."""
    wf = PatternAnalysisWorkflow()
    result = WorkflowResult(workflow_name="patterns")
    blocks = wf.report_section(result)
    assert blocks == []
