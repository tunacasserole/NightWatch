"""Tests for nightwatch.workflows.registry module."""

from __future__ import annotations

from nightwatch.workflows.base import Workflow
from nightwatch.workflows.registry import (
    _REGISTRY,
    get_enabled_workflows,
    list_registered,
    register,
)


def test_register_decorator():
    """@register adds workflow to the registry."""

    @register
    class DummyWorkflow(Workflow):
        name = "test_dummy"
        safe_outputs = []

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

    assert "test_dummy" in _REGISTRY
    assert _REGISTRY["test_dummy"] is DummyWorkflow
    # Cleanup
    del _REGISTRY["test_dummy"]


def test_list_registered_includes_builtin():
    """Built-in workflows (errors, ci_doctor, patterns) are registered."""
    # Import to trigger registration
    import nightwatch.workflows.ci_doctor  # noqa: F401
    import nightwatch.workflows.errors  # noqa: F401
    import nightwatch.workflows.patterns  # noqa: F401

    registered = list_registered()
    assert "errors" in registered
    assert "ci_doctor" in registered
    assert "patterns" in registered


def test_get_enabled_workflows_default():
    """Default (None) returns the errors workflow."""
    import nightwatch.workflows.errors  # noqa: F401

    workflows = get_enabled_workflows(None)
    assert len(workflows) == 1
    assert workflows[0].name == "errors"


def test_get_enabled_workflows_specific():
    """Specific names return matching workflows."""
    import nightwatch.workflows.ci_doctor  # noqa: F401
    import nightwatch.workflows.errors  # noqa: F401

    workflows = get_enabled_workflows(["errors", "ci_doctor"])
    names = [w.name for w in workflows]
    assert "errors" in names
    assert "ci_doctor" in names


def test_get_enabled_workflows_unknown_skipped():
    """Unknown workflow names are skipped with a warning."""
    import nightwatch.workflows.errors  # noqa: F401

    workflows = get_enabled_workflows(["errors", "nonexistent_workflow"])
    assert len(workflows) == 1
    assert workflows[0].name == "errors"
