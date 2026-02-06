"""Tests for nightwatch.workflows — ErrorAnalysisWorkflow and CIDoctorWorkflow."""

from __future__ import annotations

from unittest.mock import MagicMock

from nightwatch.workflows.base import SafeOutput, WorkflowAnalysis, WorkflowItem, WorkflowResult
from nightwatch.workflows.errors import ErrorAnalysisWorkflow
from nightwatch.workflows.ci_doctor import CIDoctorWorkflow


# ---------------------------------------------------------------------------
# ErrorAnalysisWorkflow
# ---------------------------------------------------------------------------


class TestErrorAnalysisWorkflowAnalyze:
    def test_analyze_pairs_items_with_analyses(self):
        wf = ErrorAnalysisWorkflow()
        items = [
            WorkflowItem(id="0", title="Error1", raw_data=MagicMock()),
            WorkflowItem(id="1", title="Error2", raw_data=MagicMock()),
        ]
        a1 = MagicMock(root_cause="Missing nil check", confidence=0.8, tokens_used=5000)
        a2 = MagicMock(root_cause="Bad query", confidence=0.5, tokens_used=3000)
        result = wf.analyze(items, analyses=[a1, a2])
        assert len(result) == 2
        assert result[0].summary == "Missing nil check"
        assert result[1].summary == "Bad query"

    def test_analyze_handles_none_analysis(self):
        wf = ErrorAnalysisWorkflow()
        items = [WorkflowItem(id="0", title="Error1", raw_data=MagicMock())]
        result = wf.analyze(items, analyses=[None])
        assert len(result) == 1
        assert result[0].summary == ""
        assert result[0].confidence == 0.0


class TestErrorAnalysisWorkflowAct:
    def test_act_wraps_actions(self):
        wf = ErrorAnalysisWorkflow()
        analyses = [MagicMock()]
        actions_taken = [
            {"type": SafeOutput.CREATE_ISSUE, "target": "#42", "details": {}, "success": True},
        ]
        result = wf.act(analyses, actions_taken=actions_taken)
        assert len(result) == 1
        assert result[0].action_type == SafeOutput.CREATE_ISSUE
        assert result[0].success is True

    def test_act_filters_unsafe_outputs(self):
        wf = ErrorAnalysisWorkflow()
        analyses = [MagicMock()]
        actions_taken = [
            {"type": "delete_repo", "target": "x", "details": {}, "success": True},
        ]
        result = wf.act(analyses, actions_taken=actions_taken)
        assert len(result) == 0  # "delete_repo" is not a safe output

    def test_act_empty_actions(self):
        wf = ErrorAnalysisWorkflow()
        result = wf.act([], actions_taken=[])
        assert result == []


# ---------------------------------------------------------------------------
# CIDoctorWorkflow — report_section
# ---------------------------------------------------------------------------


class TestCIDoctorReportSection:
    def test_report_section_generates_blocks(self):
        wf = CIDoctorWorkflow()
        analysis = WorkflowAnalysis(
            item=WorkflowItem(id="1", title="Build #100 failed", raw_data={}),
            summary="Flaky test detected",
            confidence=0.9,
            tokens_used=1000,
            details={"is_transient": True},
        )
        wr = WorkflowResult(
            workflow_name="ci_doctor",
            items_fetched=1,
            items_analyzed=1,
            analyses=[analysis],
            actions=[],
        )
        blocks = wf.report_section(wr)
        assert len(blocks) == 2
        assert "CI Doctor" in blocks[0]["text"]["text"]
        assert "Flaky test detected" in blocks[1]["text"]["text"]

    def test_report_section_empty_analyses(self):
        wf = CIDoctorWorkflow()
        wr = WorkflowResult(
            workflow_name="ci_doctor",
            items_fetched=0,
            items_analyzed=0,
            analyses=[],
            actions=[],
        )
        blocks = wf.report_section(wr)
        assert blocks == []

    def test_report_section_transient_emoji(self):
        wf = CIDoctorWorkflow()
        transient = WorkflowAnalysis(
            item=WorkflowItem(id="1", title="Build failed", raw_data={}),
            summary="Flaky",
            confidence=0.8,
            tokens_used=500,
            details={"is_transient": True},
        )
        non_transient = WorkflowAnalysis(
            item=WorkflowItem(id="2", title="Build failed 2", raw_data={}),
            summary="Real failure",
            confidence=0.9,
            tokens_used=500,
            details={"is_transient": False},
        )
        wr = WorkflowResult(
            workflow_name="ci_doctor",
            items_fetched=2,
            items_analyzed=2,
            analyses=[transient, non_transient],
            actions=[],
        )
        blocks = wf.report_section(wr)
        # Check emojis for transient vs non-transient
        texts = [b["text"]["text"] for b in blocks[1:]]
        assert any("\u2705" in t for t in texts)  # checkmark for transient
        assert any("\U0001f534" in t for t in texts)  # red circle for non-transient
