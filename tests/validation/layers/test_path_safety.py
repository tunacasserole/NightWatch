"""Tests for the PathSafetyValidator."""

from nightwatch.types.validation import ValidationSeverity
from nightwatch.validation.layers.path_safety import PathSafetyValidator


class FakeChange:
    def __init__(self, path):
        self.path = path


class TestPathSafetyValidator:
    def test_absolute_path_fails(self):
        v = PathSafetyValidator()
        result = v.validate([FakeChange("/etc/passwd")])
        assert not result.passed
        assert any(i.severity == ValidationSeverity.ERROR for i in result.issues)

    def test_path_traversal_fails(self):
        v = PathSafetyValidator()
        result = v.validate([FakeChange("../../etc")])
        assert not result.passed

    def test_relative_path_passes(self):
        v = PathSafetyValidator()
        result = v.validate([FakeChange("app/models/user.rb")])
        assert result.passed
