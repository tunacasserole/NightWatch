"""Tests for quality gate validation (Ralph pattern: validate before committing)."""

from unittest.mock import MagicMock

from nightwatch.models import Analysis, Confidence, FileChange
from nightwatch.validation import _check_ruby_syntax, validate_file_changes


def _make_analysis(**overrides) -> Analysis:
    """Helper to build Analysis with defaults."""
    defaults = {
        "title": "Test Error",
        "reasoning": "test reasoning",
        "root_cause": "test root cause",
        "has_fix": True,
        "confidence": Confidence.HIGH,
        "file_changes": [],
        "suggested_next_steps": [],
    }
    defaults.update(overrides)
    return Analysis(**defaults)


def _make_github_client(files: dict[str, str | None] | None = None) -> MagicMock:
    """Helper to build a mock GitHubClient.

    Args:
        files: Dict mapping path → content (or None for nonexistent).
    """
    client = MagicMock()
    files = files or {}

    def read_file(path):
        return files.get(path)

    client.read_file.side_effect = read_file
    return client


# ---------------------------------------------------------------------------
# No file changes
# ---------------------------------------------------------------------------


class TestNoFileChanges:
    def test_no_changes_is_valid(self):
        analysis = _make_analysis(file_changes=[])
        gh = _make_github_client()
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_absolute_path_rejected(self):
        analysis = _make_analysis(
            file_changes=[FileChange(path="/etc/passwd", action="modify", content="bad")]
        )
        gh = _make_github_client()
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False
        assert any("Unsafe path" in e for e in result.errors)

    def test_traversal_path_rejected(self):
        analysis = _make_analysis(
            file_changes=[FileChange(path="app/../../../etc/hosts", action="modify", content="bad")]
        )
        gh = _make_github_client()
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False
        assert any("Unsafe path" in e for e in result.errors)

    def test_normal_path_accepted(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/user.rb",
                    action="modify",
                    content="class User < ApplicationRecord\nend\n",
                )
            ]
        )
        gh = _make_github_client({"app/models/user.rb": "class User\nend\n"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Content checks
# ---------------------------------------------------------------------------


class TestContentValidation:
    def test_empty_content_for_modify_rejected(self):
        analysis = _make_analysis(
            file_changes=[FileChange(path="app/models/user.rb", action="modify", content="")]
        )
        gh = _make_github_client({"app/models/user.rb": "existing content"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False
        assert any("Empty content" in e for e in result.errors)

    def test_none_content_for_create_rejected(self):
        analysis = _make_analysis(
            file_changes=[FileChange(path="app/models/new.rb", action="create", content=None)]
        )
        gh = _make_github_client()
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False
        assert any("Empty content" in e for e in result.errors)

    def test_whitespace_only_content_rejected(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(path="app/models/user.rb", action="modify", content="   \n  \n")
            ]
        )
        gh = _make_github_client({"app/models/user.rb": "existing"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False

    def test_short_content_warning(self):
        analysis = _make_analysis(
            file_changes=[FileChange(path="app/models/user.rb", action="modify", content="short")]
        )
        gh = _make_github_client({"app/models/user.rb": "existing content"})
        result = validate_file_changes(analysis, gh)
        # Short content is a warning, not an error
        assert result.is_valid is True
        assert any("Very short content" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# File existence checks
# ---------------------------------------------------------------------------


class TestFileExistence:
    def test_modify_nonexistent_file_rejected(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/missing.rb",
                    action="modify",
                    content="class Missing\nend\n",
                )
            ]
        )
        gh = _make_github_client()  # No files exist
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False
        assert any("does not exist" in e for e in result.errors)

    def test_modify_existing_file_accepted(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/user.rb",
                    action="modify",
                    content="class User < ApplicationRecord\n  validates :name\nend\n",
                )
            ]
        )
        gh = _make_github_client({"app/models/user.rb": "class User\nend\n"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True

    def test_create_existing_file_warning(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/user.rb",
                    action="create",
                    content="class User < ApplicationRecord\nend\n",
                )
            ]
        )
        gh = _make_github_client({"app/models/user.rb": "old content"})
        result = validate_file_changes(analysis, gh)
        # Warning, not error — overwrite is sometimes intentional
        assert result.is_valid is True
        assert any("already exists" in w for w in result.warnings)

    def test_create_new_file_accepted(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/new_model.rb",
                    action="create",
                    content="class NewModel < ApplicationRecord\nend\n",
                )
            ]
        )
        gh = _make_github_client()  # File doesn't exist
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Ruby syntax checks
# ---------------------------------------------------------------------------


class TestCheckRubySyntax:
    def test_balanced_class_def_end(self):
        content = """class User < ApplicationRecord
  def full_name
    "#{first_name} #{last_name}"
  end
end
"""
        issues = _check_ruby_syntax(content)
        assert issues == []

    def test_missing_end(self):
        content = """class User < ApplicationRecord
  def full_name
    "#{first_name} #{last_name}"
  end
"""
        issues = _check_ruby_syntax(content)
        # Within tolerance of 2, so this 1-off shouldn't trigger
        assert issues == []

    def test_no_end_at_all(self):
        content = """class User < ApplicationRecord
  def full_name
    "#{first_name} #{last_name}"
"""
        issues = _check_ruby_syntax(content)
        assert len(issues) > 0
        assert any("no 'end'" in issue for issue in issues)

    def test_severely_imbalanced(self):
        content = """class User < ApplicationRecord
  def method1
  def method2
  def method3
  def method4
end
"""
        issues = _check_ruby_syntax(content)
        assert len(issues) > 0
        assert any("imbalanced" in issue for issue in issues)

    def test_empty_string_no_issues(self):
        issues = _check_ruby_syntax("")
        assert issues == []

    def test_comments_ignored(self):
        content = """# class Foo
# def bar
# end
class Real
  def method
  end
end
"""
        issues = _check_ruby_syntax(content)
        assert issues == []

    def test_non_ruby_file_not_checked(self):
        """Validation only checks .rb files — non-Ruby files skip syntax check."""
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="config/database.yml",
                    action="modify",
                    content="production:\n  adapter: postgresql\n",
                )
            ]
        )
        gh = _make_github_client({"config/database.yml": "old config"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True
        assert result.errors == []


# ---------------------------------------------------------------------------
# Multiple file changes
# ---------------------------------------------------------------------------


class TestMultipleChanges:
    def test_one_bad_one_good(self):
        """If any change has errors, the whole result is invalid."""
        analysis = _make_analysis(
            file_changes=[
                FileChange(path="/etc/passwd", action="modify", content="bad"),
                FileChange(
                    path="app/models/user.rb",
                    action="modify",
                    content="class User\nend\n",
                ),
            ]
        )
        gh = _make_github_client({"app/models/user.rb": "existing"})
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is False

    def test_all_good(self):
        analysis = _make_analysis(
            file_changes=[
                FileChange(
                    path="app/models/user.rb",
                    action="modify",
                    content="class User\n  validates :name\nend\n",
                ),
                FileChange(
                    path="app/models/product.rb",
                    action="modify",
                    content="class Product\n  validates :title\nend\n",
                ),
            ]
        )
        gh = _make_github_client({
            "app/models/user.rb": "old user",
            "app/models/product.rb": "old product",
        })
        result = validate_file_changes(analysis, gh)
        assert result.is_valid is True
