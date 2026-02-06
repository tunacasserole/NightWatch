"""Tests for nightwatch.workflows.errors module."""

from __future__ import annotations

from nightwatch.workflows.base import SafeOutput
from nightwatch.workflows.errors import ErrorAnalysisWorkflow


def test_error_workflow_registration():
    """ErrorAnalysisWorkflow is properly registered."""
    wf = ErrorAnalysisWorkflow()
    assert wf.name == "errors"


def test_error_workflow_safe_outputs():
    """ErrorAnalysisWorkflow has correct safe outputs."""
    wf = ErrorAnalysisWorkflow()
    assert SafeOutput.CREATE_ISSUE in wf.safe_outputs
    assert SafeOutput.CREATE_PR in wf.safe_outputs
    assert SafeOutput.SEND_SLACK in wf.safe_outputs
    assert SafeOutput.ADD_COMMENT not in wf.safe_outputs


def test_error_workflow_fetch_with_items():
    """fetch() wraps raw items into WorkflowItems."""

    class FakeError:
        error_class = "RuntimeError"
        transaction = "Controller/test"

    wf = ErrorAnalysisWorkflow()
    items = wf.fetch(items=[FakeError(), FakeError()])
    assert len(items) == 2
    assert "RuntimeError" in items[0].title
    assert "Controller/test" in items[0].title


def test_error_workflow_fetch_empty():
    """fetch() returns empty list when no items."""
    wf = ErrorAnalysisWorkflow()
    assert wf.fetch() == []


def test_error_workflow_filter_limits():
    """filter() respects max_errors limit."""
    wf = ErrorAnalysisWorkflow()
    from nightwatch.workflows.base import WorkflowItem

    items = [WorkflowItem(id=str(i), title=f"Error {i}") for i in range(10)]
    filtered = wf.filter(items, max_errors=3)
    assert len(filtered) == 3


def test_error_workflow_filter_no_limit():
    """filter() returns all when no limit specified."""
    wf = ErrorAnalysisWorkflow()
    from nightwatch.workflows.base import WorkflowItem

    items = [WorkflowItem(id=str(i), title=f"Error {i}") for i in range(5)]
    filtered = wf.filter(items)
    assert len(filtered) == 5


def test_error_workflow_report_section():
    """report_section() generates Slack blocks."""
    from nightwatch.workflows.base import WorkflowAnalysis, WorkflowItem, WorkflowResult

    wf = ErrorAnalysisWorkflow()
    result = WorkflowResult(
        workflow_name="errors",
        items_analyzed=2,
        analyses=[
            WorkflowAnalysis(
                item=WorkflowItem(id="1", title="Error A"),
                summary="Root cause A",
            ),
            WorkflowAnalysis(
                item=WorkflowItem(id="2", title="Error B"),
                summary="Root cause B",
            ),
        ],
    )
    blocks = wf.report_section(result)
    assert len(blocks) >= 1
    assert blocks[0]["type"] == "section"
    assert "2 errors analyzed" in blocks[0]["text"]["text"]
