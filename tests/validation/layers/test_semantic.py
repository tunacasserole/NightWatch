"""Tests for the SemanticValidator."""

from nightwatch.validation.layers.semantic import SemanticValidator


class FakeChange:
    def __init__(self, path):
        self.path = path
        self.action = "modify"
        self.content = "content"


class TestSemanticValidator:
    def test_changes_match_root_cause_modules(self):
        v = SemanticValidator()
        result = v.validate(
            [FakeChange("app/models/user.rb")],
            context={
                "root_cause": "Bug in app models layer",
                "reasoning": "Found issue in user model",
            },
        )
        assert result.passed
        assert len([i for i in result.issues if i.severity.value == "warning"]) == 0

    def test_too_many_changes_warns(self):
        v = SemanticValidator()
        changes = [FakeChange(f"file{i}.rb") for i in range(6)]
        result = v.validate(
            changes,
            context={"root_cause": "some bug", "reasoning": "yes"},
        )
        assert result.passed  # warnings don't fail
        assert len(result.issues) > 0
