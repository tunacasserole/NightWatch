"""Tests for the ValidationOrchestrator."""

from nightwatch.validation.layers.path_safety import PathSafetyValidator
from nightwatch.validation.orchestrator import ValidationOrchestrator


class FakeChange:
    def __init__(
        self,
        path="app/models/user.rb",
        action="modify",
        content="class User\n  def name\n    @name\n  end\nend",
    ):
        self.path = path
        self.action = action
        self.content = content


class TestValidationOrchestrator:
    def test_all_layers_run_on_valid_input(self):
        orch = ValidationOrchestrator()
        result = orch.validate(
            [FakeChange()],
            context={
                "root_cause": "user model bug",
                "confidence": "high",
                "reasoning": "found issue",
            },
        )
        assert len(result.layers) == 5
        assert result.valid

    def test_short_circuit_on_path_safety(self):
        orch = ValidationOrchestrator()
        result = orch.validate([FakeChange(path="/etc/passwd")])
        assert len(result.layers) == 1
        assert not result.valid

    def test_custom_layer_order(self):
        orch = ValidationOrchestrator(layers=[PathSafetyValidator()])
        result = orch.validate([FakeChange()])
        assert len(result.layers) == 1

    def test_blocking_errors_aggregated(self):
        orch = ValidationOrchestrator()
        result = orch.validate([FakeChange(path="/bad", action="modify", content="")])
        assert not result.valid
        assert len(result.blocking_errors) > 0

    def test_valid_true_when_no_errors(self):
        orch = ValidationOrchestrator()
        result = orch.validate(
            [FakeChange()],
            context={
                "root_cause": "user bug",
                "confidence": "high",
                "reasoning": "yes",
            },
        )
        assert result.valid
