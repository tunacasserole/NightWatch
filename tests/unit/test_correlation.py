"""Tests for nightwatch.correlation — PR correlation, search terms, formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from github import GithubException

from nightwatch.correlation import (
    _camel_to_snake,
    _extract_search_terms,
    _time_ago,
    correlate_error_with_prs,
    fetch_recent_merged_prs,
    format_correlated_prs,
)
from tests.factories import make_correlated_pr, make_error_group


class TestFetchRecentMergedPrs:
    def test_returns_merged_prs(self):
        mock_repo = MagicMock()
        merged_at = datetime.now(UTC) - timedelta(hours=2)
        pr = MagicMock()
        pr.merged_at = merged_at
        pr.number = 50
        pr.title = "Fix product display"
        pr.html_url = "http://gh/pull/50"
        file_mock = MagicMock(filename="app/models/product.rb")
        pr.get_files.return_value = [file_mock]

        mock_repo.get_pulls.return_value = [pr]
        results = fetch_recent_merged_prs(mock_repo, hours=24)
        assert len(results) == 1
        assert results[0].number == 50
        assert "product.rb" in results[0].changed_files[0]

    def test_skips_unmerged_prs(self):
        mock_repo = MagicMock()
        pr = MagicMock()
        pr.merged_at = None
        mock_repo.get_pulls.return_value = [pr]
        results = fetch_recent_merged_prs(mock_repo)
        assert results == []

    def test_stops_at_window_boundary(self):
        mock_repo = MagicMock()
        old_pr = MagicMock()
        old_pr.merged_at = datetime.now(UTC) - timedelta(hours=48)
        mock_repo.get_pulls.return_value = [old_pr]
        results = fetch_recent_merged_prs(mock_repo, hours=24)
        assert results == []

    def test_caps_at_10_results(self):
        mock_repo = MagicMock()
        prs = []
        for i in range(15):
            pr = MagicMock()
            pr.merged_at = datetime.now(UTC) - timedelta(minutes=i)
            pr.number = i
            pr.title = f"PR {i}"
            pr.html_url = f"http://gh/pull/{i}"
            pr.get_files.return_value = []
            prs.append(pr)
        mock_repo.get_pulls.return_value = prs
        results = fetch_recent_merged_prs(mock_repo)
        assert len(results) == 10

    def test_handles_api_error(self):
        mock_repo = MagicMock()
        mock_repo.get_pulls.side_effect = GithubException(status=500, data={}, headers={})
        results = fetch_recent_merged_prs(mock_repo)
        assert results == []

    def test_handles_get_files_error(self):
        mock_repo = MagicMock()
        pr = MagicMock()
        pr.merged_at = datetime.now(UTC) - timedelta(hours=1)
        pr.number = 1
        pr.title = "PR 1"
        pr.html_url = "http://gh/pull/1"
        pr.get_files.side_effect = GithubException(status=500, data={}, headers={})
        mock_repo.get_pulls.return_value = [pr]
        results = fetch_recent_merged_prs(mock_repo)
        assert len(results) == 1
        assert results[0].changed_files == []

    def test_naive_merged_at_gets_utc(self):
        mock_repo = MagicMock()
        pr = MagicMock()
        pr.merged_at = datetime.now() - timedelta(hours=1)  # naive datetime
        pr.merged_at = pr.merged_at.replace(tzinfo=None)
        pr.number = 1
        pr.title = "PR 1"
        pr.html_url = "http://gh/pull/1"
        pr.get_files.return_value = []
        mock_repo.get_pulls.return_value = [pr]
        results = fetch_recent_merged_prs(mock_repo)
        assert len(results) == 1


class TestCorrelateErrorWithPrs:
    def test_matches_by_file_overlap(self):
        error = make_error_group(
            error_class="NoMethodError",
            transaction="Controller/products/show",
        )
        pr = make_correlated_pr(changed_files=["app/controllers/products_controller.rb"])
        related = correlate_error_with_prs(error, [pr])
        assert len(related) == 1
        assert related[0].overlap_score > 0

    def test_no_match(self):
        error = make_error_group(
            error_class="NoMethodError",
            transaction="Controller/products/show",
        )
        pr = make_correlated_pr(changed_files=["app/models/user.rb"])
        related = correlate_error_with_prs(error, [pr])
        assert related == []

    def test_sorts_by_overlap_descending(self):
        error = make_error_group(transaction="Controller/products/show")
        pr1 = make_correlated_pr(
            number=1,
            changed_files=["app/controllers/products_controller.rb"],
        )
        pr2 = make_correlated_pr(
            number=2,
            changed_files=[
                "app/controllers/products_controller.rb",
                "app/models/product.rb",
            ],
        )
        related = correlate_error_with_prs(error, [pr1, pr2])
        assert related[0].number == 2  # More overlap

    def test_empty_search_terms_returns_empty(self):
        error = make_error_group(error_class="", transaction="")
        pr = make_correlated_pr()
        assert correlate_error_with_prs(error, [pr]) == []


class TestFormatCorrelatedPrs:
    def test_formats_markdown_table(self):
        pr = make_correlated_pr(number=50, title="Fix product display", overlap_score=0.75)
        result = format_correlated_prs([pr])
        assert "## Recent Related Changes" in result
        assert "#50" in result
        assert "75%" in result

    def test_empty_list_returns_none(self):
        assert format_correlated_prs([]) is None

    def test_caps_at_5_prs(self):
        prs = [make_correlated_pr(number=i, overlap_score=0.5) for i in range(10)]
        result = format_correlated_prs(prs)
        assert result.count("| [#") == 5

    def test_truncates_long_titles(self):
        pr = make_correlated_pr(title="x" * 100, overlap_score=0.5)
        result = format_correlated_prs([pr])
        assert "..." in result


class TestExtractSearchTerms:
    def test_transaction_parsing(self):
        terms = _extract_search_terms("", "Controller/products/show")
        assert "products" in terms
        assert "show" in terms

    def test_error_class_parsing(self):
        terms = _extract_search_terms("ProductsController::NotFoundError", "")
        assert "products_controller" in terms or "products" in terms

    def test_filters_short_terms(self):
        terms = _extract_search_terms("", "Controller/a/b")
        assert all(len(t) > 2 for t in terms)

    def test_empty_inputs(self):
        terms = _extract_search_terms("", "")
        assert terms == []

    def test_singular_forms_generated(self):
        terms = _extract_search_terms("", "Controller/products/show")
        assert "product" in terms  # singular of products


class TestCamelToSnake:
    def test_simple(self):
        assert _camel_to_snake("ProductsController") == "products_controller"

    def test_multi_caps(self):
        assert _camel_to_snake("HTTPSConnection") == "https_connection"

    def test_already_snake(self):
        assert _camel_to_snake("already_snake") == "already_snake"

    def test_single_word(self):
        assert _camel_to_snake("Product") == "product"


class TestTimeAgo:
    def test_minutes_ago(self):
        now = datetime.now(UTC)
        iso = (now - timedelta(minutes=30)).isoformat()
        result = _time_ago(iso, now)
        assert result == "30m ago"

    def test_hours_ago(self):
        now = datetime.now(UTC)
        iso = (now - timedelta(hours=5)).isoformat()
        result = _time_ago(iso, now)
        assert result == "5h ago"

    def test_days_ago(self):
        now = datetime.now(UTC)
        iso = (now - timedelta(days=3)).isoformat()
        result = _time_ago(iso, now)
        assert result == "3d ago"

    def test_invalid_iso_returns_question_mark(self):
        assert _time_ago("not-a-date", datetime.now(UTC)) == "?"

    def test_none_returns_question_mark(self):
        assert _time_ago(None, datetime.now(UTC)) == "?"
