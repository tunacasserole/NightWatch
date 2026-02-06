"""Tests for nightwatch.workflows.base module."""

from __future__ import annotations

from nightwatch.workflows.base import (
    SafeOutput,
    Workflow,
    WorkflowAction,
    WorkflowAnalysis,
    WorkflowItem,
    WorkflowResult,
)


def test_safe_output_enum_values():
    """SafeOutput has the expected action types."""
    assert SafeOutput.CREATE_ISSUE == "create_issue"
    assert SafeOutput.CREATE_PR == "create_pr"
    assert SafeOutput.ADD_COMMENT == "add_comment"
    assert SafeOutput.ADD_LABEL == "add_label"
    assert SafeOutput.SEND_SLACK == "send_slack"
    assert SafeOutput.WRITE_FILE == "write_file"


def test_workflow_item_construction():
    """WorkflowItem holds basic item data."""
    item = WorkflowItem(id="1", title="Test Error")
    assert item.id == "1"
    assert item.title == "Test Error"
    assert item.raw_data is None
    assert item.metadata == {}


def test_workflow_item_with_metadata():
    """WorkflowItem accepts raw_data and metadata."""
    item = WorkflowItem(
        id="2",
        title="Another Error",
        raw_data={"key": "value"},
        metadata={"count": 5},
    )
    assert item.raw_data == {"key": "value"}
    assert item.metadata["count"] == 5


def test_workflow_analysis_defaults():
    """WorkflowAnalysis has sensible defaults."""
    item = WorkflowItem(id="1", title="Test")
    analysis = WorkflowAnalysis(item=item)
    assert analysis.summary == ""
    assert analysis.details == {}
    assert analysis.confidence == 0.0
    assert analysis.tokens_used == 0


def test_workflow_action_defaults():
    """WorkflowAction stores action type and result."""
    action = WorkflowAction(action_type=SafeOutput.CREATE_ISSUE)
    assert action.action_type == SafeOutput.CREATE_ISSUE
    assert action.target == ""
    assert action.success is False


def test_workflow_result_defaults():
    """WorkflowResult aggregates workflow execution data."""
    result = WorkflowResult(workflow_name="test")
    assert result.workflow_name == "test"
    assert result.items_fetched == 0
    assert result.items_analyzed == 0
    assert result.analyses == []
    assert result.actions == []
    assert result.errors == []


def test_check_safe_output_allows_registered():
    """check_safe_output returns True for allowed actions."""

    class TestWorkflow(Workflow):
        name = "test"
        safe_outputs = [SafeOutput.CREATE_ISSUE, SafeOutput.SEND_SLACK]

        def fetch(self, **kwargs):
            return []

        def filter(self, items, **kwargs):
            return items

        def analyze(self, items, **kwargs):
            return []

        def act(self, analyses, **kwargs):
            return []

        def report_section(self, result):
            return []

    wf = TestWorkflow()
    assert wf.check_safe_output(SafeOutput.CREATE_ISSUE) is True
    assert wf.check_safe_output(SafeOutput.SEND_SLACK) is True


def test_check_safe_output_blocks_unauthorized():
    """check_safe_output returns False for disallowed actions."""

    class RestrictedWorkflow(Workflow):
        name = "restricted"
        safe_outputs = [SafeOutput.ADD_COMMENT]

        def fetch(self, **kwargs):
            return []

        def filter(self, items, **kwargs):
            return items

        def analyze(self, items, **kwargs):
            return []

        def act(self, analyses, **kwargs):
            return []

        def report_section(self, result):
            return []

    wf = RestrictedWorkflow()
    assert wf.check_safe_output(SafeOutput.ADD_COMMENT) is True
    assert wf.check_safe_output(SafeOutput.CREATE_ISSUE) is False
    assert wf.check_safe_output(SafeOutput.CREATE_PR) is False
