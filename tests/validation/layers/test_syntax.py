"""Tests for the SyntaxValidator."""

from nightwatch.validation.layers.syntax import SyntaxValidator


class FakeChange:
    def __init__(self, path, content):
        self.path = path
        self.action = "modify"
        self.content = content


class TestSyntaxValidator:
    def test_balanced_ruby_blocks(self):
        v = SyntaxValidator()
        result = v.validate(
            [
                FakeChange(
                    "app/models/user.rb",
                    "class User\n  def name\n    @name\n  end\nend",
                )
            ]
        )
        assert result.passed

    def test_unbalanced_ruby_blocks(self):
        v = SyntaxValidator()
        result = v.validate(
            [
                FakeChange(
                    "app/models/user.rb",
                    "class User\n  def name\n    @name\n  ",
                )
            ]
        )
        assert not result.passed

    def test_non_ruby_skipped(self):
        v = SyntaxValidator()
        result = v.validate([FakeChange("app/main.py", "def foo():\n    pass")])
        assert result.passed
