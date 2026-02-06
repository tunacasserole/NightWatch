"""Tests for nightwatch.github — GitHubClient class, CodeCache, issue/PR operations."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from nightwatch.github import CodeCache, GitHubClient
from tests.factories import (
    make_analysis,
    make_error_analysis_result,
    make_error_group,
)

# ---------------------------------------------------------------------------
# CodeCache
# ---------------------------------------------------------------------------


class TestCodeCache:
    def test_set_and_get(self):
        cache = CodeCache(ttl_minutes=30)
        cache.set("file.rb", "content")
        assert cache.get("file.rb") == "content"

    def test_miss_returns_none(self):
        cache = CodeCache()
        assert cache.get("missing") is None

    def test_expired_entry_returns_none(self):
        cache = CodeCache(ttl_minutes=0)  # Immediate expiry
        cache.set("file.rb", "content")
        # TTL is 0 minutes so it's immediately expired
        assert cache.get("file.rb") is None

    def test_stats_tracks_hits_and_misses(self):
        cache = CodeCache()
        cache.set("a", "1")
        cache.get("a")  # hit
        cache.get("b")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_requests"] == 2
        assert stats["hit_rate"] == 0.5
        assert stats["cached_files"] == 1

    def test_stats_empty_cache(self):
        cache = CodeCache()
        stats = cache.stats
        assert stats["total_requests"] == 0
        assert stats["hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# GitHubClient — code tools
# ---------------------------------------------------------------------------


class TestGitHubClientReadFile:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_read_file_decodes_content(self, client):
        content_file = MagicMock()
        content_file.content = base64.b64encode(b"class Product\nend").decode()
        self.mock_repo.get_contents.return_value = content_file
        result = client.read_file("app/models/product.rb")
        assert "class Product" in result

    def test_read_file_directory_returns_none(self, client):
        self.mock_repo.get_contents.return_value = [MagicMock(), MagicMock()]
        assert client.read_file("app/models") is None

    def test_read_file_404_returns_none(self, client):
        self.mock_repo.get_contents.side_effect = GithubException(
            status=404, data={"message": "Not Found"}, headers={}
        )
        assert client.read_file("nonexistent.rb") is None

    def test_read_file_other_error_raises(self, client):
        self.mock_repo.get_contents.side_effect = GithubException(
            status=500, data={"message": "Server Error"}, headers={}
        )
        with pytest.raises(GithubException):
            client.read_file("file.rb")


class TestGitHubClientSearchCode:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_gh_instance = mock_gh.return_value
            self.mock_repo = MagicMock()
            self.mock_gh_instance.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_returns_results(self, client):
        item = MagicMock(path="app/models/product.rb", name="product.rb", html_url="http://gh/p.rb")
        self.mock_gh_instance.search_code.return_value = iter([item])
        results = client.search_code("Product")
        assert len(results) == 1
        assert results[0]["path"] == "app/models/product.rb"

    def test_with_extension(self, client):
        self.mock_gh_instance.search_code.return_value = iter([])
        client.search_code("Product", file_extension="rb")
        call_args = self.mock_gh_instance.search_code.call_args[0][0]
        assert "extension:rb" in call_args

    def test_handles_api_error(self, client):
        self.mock_gh_instance.search_code.side_effect = GithubException(
            status=422, data={"message": "Validation Failed"}, headers={}
        )
        assert client.search_code("bad query") == []

    def test_limits_to_20_results(self, client):
        items = [
            MagicMock(path=f"file{i}.rb", name=f"file{i}.rb", html_url=f"http://gh/{i}")
            for i in range(30)
        ]
        self.mock_gh_instance.search_code.return_value = iter(items)
        results = client.search_code("common")
        assert len(results) == 20


class TestGitHubClientListDirectory:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_lists_files(self, client):
        items = [
            MagicMock(name="product.rb", path="app/models/product.rb", type="file"),
            MagicMock(name="concerns", path="app/models/concerns", type="dir"),
        ]
        self.mock_repo.get_contents.return_value = items
        result = client.list_directory("app/models")
        assert len(result) == 2
        assert result[0]["name"] == "product.rb"
        assert result[1]["type"] == "dir"

    def test_404_returns_empty(self, client):
        self.mock_repo.get_contents.side_effect = GithubException(
            status=404, data={"message": "Not Found"}, headers={}
        )
        assert client.list_directory("nonexistent") == []


# ---------------------------------------------------------------------------
# GitHubClient — find_existing_issue
# ---------------------------------------------------------------------------


class TestFindExistingIssue:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def _make_issue(self, title, body=""):
        issue = MagicMock()
        issue.title = title
        issue.body = body
        return issue

    def test_exact_match(self, client):
        error = make_error_group(
            error_class="NoMethodError",
            transaction="Controller/products/show",
        )
        issue = self._make_issue(
            "NoMethodError in products/show",
            "Transaction: Controller/products/show",
        )
        self.mock_repo.get_issues.return_value = [issue]
        result = client.find_existing_issue(error)
        assert result is issue

    def test_class_only_match(self, client):
        error = make_error_group(error_class="NoMethodError", transaction="Controller/other/action")
        issue = self._make_issue("NoMethodError in old/action")
        self.mock_repo.get_issues.return_value = [issue]
        result = client.find_existing_issue(error)
        assert result is issue

    def test_no_match(self, client):
        error = make_error_group(error_class="NoMethodError", transaction="Controller/products/show")
        issue = self._make_issue("TypeError in orders/create")
        self.mock_repo.get_issues.return_value = [issue]
        result = client.find_existing_issue(error)
        assert result is None

    def test_no_class_no_transaction_returns_none(self, client):
        error = make_error_group(error_class="", transaction="")
        assert client.find_existing_issue(error) is None


# ---------------------------------------------------------------------------
# GitHubClient — create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_creates_issue_and_returns_result(self, client):
        result = make_error_analysis_result()
        mock_issue = MagicMock(number=42, html_url="http://gh/issues/42")
        self.mock_repo.create_issue.return_value = mock_issue

        created = client.create_issue(result)
        assert created.issue_number == 42
        assert created.action == "created"
        self.mock_repo.create_issue.assert_called_once()

    def test_includes_correlated_prs_section(self, client):
        result = make_error_analysis_result()
        mock_issue = MagicMock(number=42, html_url="http://gh/issues/42")
        self.mock_repo.create_issue.return_value = mock_issue

        client.create_issue(result, correlated_prs_section="## Related PRs\n| PR | Title |")
        call_kwargs = self.mock_repo.create_issue.call_args
        assert "Related PRs" in call_kwargs.kwargs["body"]


# ---------------------------------------------------------------------------
# GitHubClient — add_occurrence_comment
# ---------------------------------------------------------------------------


class TestAddOccurrenceComment:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_adds_comment(self, client):
        issue = MagicMock(number=42, html_url="http://gh/issues/42")
        error = make_error_group()
        result = client.add_occurrence_comment(issue, error)
        assert result.action == "commented"
        assert result.issue_number == 42
        issue.create_comment.assert_called_once()

    def test_includes_analysis_reasoning(self, client):
        issue = MagicMock(number=42, html_url="http://gh/issues/42")
        error = make_error_group()
        analysis = make_analysis(reasoning="Root cause is X.")
        client.add_occurrence_comment(issue, error, analysis=analysis)
        body = issue.create_comment.call_args[0][0]
        assert "Root cause is X." in body


# ---------------------------------------------------------------------------
# GitHubClient — open issue count
# ---------------------------------------------------------------------------


class TestGetOpenNightwatchIssueCount:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.github.Github") as mock_gh:
            self.mock_repo = MagicMock()
            mock_gh.return_value.get_repo.return_value = self.mock_repo
            c = GitHubClient()
            c._repo = self.mock_repo
            yield c

    def test_counts_issues(self, client):
        self.mock_repo.get_issues.return_value = [MagicMock(), MagicMock(), MagicMock()]
        assert client.get_open_nightwatch_issue_count() == 3

    def test_handles_api_error(self, client):
        self.mock_repo.get_issues.side_effect = GithubException(
            status=500, data={}, headers={}
        )
        assert client.get_open_nightwatch_issue_count() == 0
