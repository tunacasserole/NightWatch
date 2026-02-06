"""Tests for the QualityValidator."""

from nightwatch.validation.layers.quality import QualityValidator


class FakeChange:
    def __init__(self):
        self.path = "app/user.rb"
        self.action = "modify"
        self.content = "class User; end"


class TestQualityValidator:
    def test_low_confidence_fails(self):
        v = QualityValidator()
        result = v.validate(
            [FakeChange()],
            context={
                "confidence": "low",
                "root_cause": "bug",
                "reasoning": "yes",
            },
        )
        assert not result.passed

    def test_missing_root_cause_fails(self):
        v = QualityValidator()
        result = v.validate(
            [FakeChange()],
            context={
                "confidence": "high",
                "root_cause": "",
                "reasoning": "yes",
            },
        )
        assert not result.passed
