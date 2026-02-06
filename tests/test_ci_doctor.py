"""Tests for nightwatch.workflows.ci_doctor module."""

from __future__ import annotations

from nightwatch.workflows.base import SafeOutput, WorkflowItem
from nightwatch.workflows.ci_doctor import CIDoctorWorkflow


def test_ci_doctor_registration():
    """CIDoctorWorkflow is properly registered."""
    wf = CIDoctorWorkflow()
    assert wf.name == "ci_doctor"


def test_ci_doctor_safe_outputs():
    """CIDoctorWorkflow cannot create issues or PRs."""
    wf = CIDoctorWorkflow()
    assert SafeOutput.ADD_COMMENT in wf.safe_outputs
    assert SafeOutput.ADD_LABEL in wf.safe_outputs
    assert SafeOutput.SEND_SLACK in wf.safe_outputs
    assert SafeOutput.CREATE_ISSUE not in wf.safe_outputs
    assert SafeOutput.CREATE_PR not in wf.safe_outputs


def test_known_patterns_network_timeout():
    """Network timeout pattern is detected."""
    wf = CIDoctorWorkflow()
    result = wf._check_known_patterns("Error: ETIMEDOUT connecting to registry")
    assert result is not None
    assert result["category"] == "infrastructure"
    assert result["is_transient"] is True


def test_known_patterns_rate_limit():
    """Rate limit pattern is detected."""
    wf = CIDoctorWorkflow()
    result = wf._check_known_patterns("API rate limit exceeded for user")
    assert result is not None
    assert result["category"] == "rate_limit"
    assert result["confidence"] == 0.95


def test_known_patterns_disk_full():
    """Disk space pattern is detected."""
    wf = CIDoctorWorkflow()
    result = wf._check_known_patterns("No space left on device")
    assert result is not None
    assert result["category"] == "resource_limit"
    assert result["is_transient"] is False


def test_known_patterns_oom():
    """OOM pattern is detected."""
    wf = CIDoctorWorkflow()
    result = wf._check_known_patterns("Process was OOMKilled")
    assert result is not None
    assert "memory" in result["root_cause"].lower()


def test_known_patterns_no_match():
    """Unrecognized error returns None."""
    wf = CIDoctorWorkflow()
    result = wf._check_known_patterns("RSpec test failed: expected 4, got 5")
    assert result is None


def test_ci_doctor_analyze_known_pattern():
    """analyze() uses known patterns for instant diagnosis."""
    wf = CIDoctorWorkflow()
    items = [
        WorkflowItem(
            id="1",
            title="Build #42",
            metadata={"log_text": "Error: ETIMEDOUT connecting to npm registry"},
        )
    ]
    analyses = wf.analyze(items)
    assert len(analyses) == 1
    assert analyses[0].confidence > 0.5
    assert "timeout" in analyses[0].summary.lower() or "network" in analyses[0].summary.lower()


def test_ci_doctor_analyze_unknown():
    """analyze() returns low confidence for unknown failures."""
    wf = CIDoctorWorkflow()
    items = [
        WorkflowItem(
            id="1",
            title="Build #42",
            metadata={"log_text": "undefined local variable 'foo'"},
        )
    ]
    analyses = wf.analyze(items)
    assert len(analyses) == 1
    assert analyses[0].confidence == 0.0
    assert "deeper analysis" in analyses[0].summary.lower()


def test_ci_doctor_filter_prioritizes_main():
    """filter() sorts main/master branch failures first."""
    wf = CIDoctorWorkflow()
    items = [
        WorkflowItem(id="1", title="Feature branch", metadata={"branch": "feature/x"}),
        WorkflowItem(id="2", title="Main branch", metadata={"branch": "main"}),
        WorkflowItem(id="3", title="Another feature", metadata={"branch": "fix/y"}),
    ]
    filtered = wf.filter(items, max_items=2)
    assert len(filtered) == 2
    assert filtered[0].metadata["branch"] == "main"


def test_ci_doctor_act_dry_run():
    """act() in dry_run mode doesn't mark actions as successful."""
    from nightwatch.workflows.base import WorkflowAnalysis

    wf = CIDoctorWorkflow()
    analyses = [
        WorkflowAnalysis(
            item=WorkflowItem(id="1", title="Build #42"),
            summary="Network timeout",
            details={"category": "infrastructure", "suggested_fix": "Retry"},
            confidence=0.95,
        )
    ]
    actions = wf.act(analyses, dry_run=True)
    assert len(actions) == 1
    assert actions[0].action_type == SafeOutput.ADD_COMMENT
    assert actions[0].success is False  # dry_run


def test_ci_doctor_diagnosis_comment_format():
    """_build_diagnosis_comment produces markdown table."""
    from nightwatch.workflows.base import WorkflowAnalysis

    wf = CIDoctorWorkflow()
    analysis = WorkflowAnalysis(
        item=WorkflowItem(id="1", title="Build #42"),
        summary="Network timeout",
        details={
            "category": "infrastructure",
            "suggested_fix": "Retry the workflow",
            "is_transient": True,
        },
        confidence=0.95,
    )
    comment = wf._build_diagnosis_comment(analysis)
    assert "NightWatch CI Diagnosis" in comment
    assert "Network timeout" in comment
    assert "infrastructure" in comment
    assert "95%" in comment


def test_ci_doctor_report_section_empty():
    """report_section returns empty for no analyses."""
    from nightwatch.workflows.base import WorkflowResult

    wf = CIDoctorWorkflow()
    result = WorkflowResult(workflow_name="ci_doctor")
    blocks = wf.report_section(result)
    assert blocks == []
