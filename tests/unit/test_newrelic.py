"""Tests for nightwatch.newrelic — NewRelicClient, NRQL queries, fetch_errors, fetch_traces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nightwatch.newrelic import NewRelicClient, _escape_nrql, load_ignore_patterns
from tests.factories import make_error_group, make_graphql_response, make_nrql_error_row


class TestNewRelicClient:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.newrelic.httpx.Client") as mock_httpx:
            self.mock_http = mock_httpx.return_value
            nr = NewRelicClient()
            yield nr

    def test_init_sets_account_info(self, client):
        assert client.account_id == "12345"
        assert client.app_name == "TestApp"

    def test_close(self, client):
        client.close()
        self.mock_http.close.assert_called_once()


class TestQueryNrql:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.newrelic.httpx.Client") as mock_httpx:
            self.mock_http = mock_httpx.return_value
            nr = NewRelicClient()
            yield nr

    def test_returns_results(self, client):
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response([{"count": 42}]),
            raise_for_status=lambda: None,
        )
        results = client.query_nrql("SELECT count(*) FROM TransactionError")
        assert results == [{"count": 42}]

    def test_empty_results(self, client):
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response([]),
            raise_for_status=lambda: None,
        )
        results = client.query_nrql("SELECT count(*) FROM TransactionError")
        assert results == []

    def test_graphql_error_returns_empty(self, client):
        self.mock_http.post.return_value = MagicMock(
            json=lambda: {"errors": [{"message": "query failed"}]},
            raise_for_status=lambda: None,
        )
        results = client.query_nrql("BAD QUERY")
        assert results == []

    def test_deeply_nested_response(self, client):
        """Handles missing keys at any nesting level."""
        self.mock_http.post.return_value = MagicMock(
            json=lambda: {"data": {}},
            raise_for_status=lambda: None,
        )
        results = client.query_nrql("SELECT 1")
        assert results == []


class TestFetchErrors:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.newrelic.httpx.Client") as mock_httpx:
            self.mock_http = mock_httpx.return_value
            nr = NewRelicClient()
            yield nr

    def test_parses_error_groups(self, client):
        rows = [
            make_nrql_error_row(
                error_class="NoMethodError",
                transaction="Controller/products/show",
                occurrences=42,
            ),
            make_nrql_error_row(
                error_class="TypeError",
                transaction="Controller/orders/create",
                occurrences=10,
            ),
        ]
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response(rows),
            raise_for_status=lambda: None,
        )
        groups = client.fetch_errors("24h")
        assert len(groups) == 2
        assert groups[0].error_class == "NoMethodError"
        assert groups[0].occurrences == 42
        assert groups[1].error_class == "TypeError"

    def test_handles_empty_results(self, client):
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response([]),
            raise_for_status=lambda: None,
        )
        groups = client.fetch_errors("1h")
        assert groups == []

    def test_fallback_to_facet(self, client):
        """When error_class/transaction not in row, falls back to facet array."""
        row = {
            "occurrences": 5,
            "error_message": "oops",
            "last_seen": "1000000",
            "facet": ["FallbackError", "Controller/fallback/action"],
        }
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response([row]),
            raise_for_status=lambda: None,
        )
        groups = client.fetch_errors("1h")
        assert len(groups) == 1
        assert groups[0].error_class == "FallbackError"
        assert groups[0].transaction == "Controller/fallback/action"

    def test_message_truncated_to_500(self, client):
        row = make_nrql_error_row(error_message="x" * 1000)
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response([row]),
            raise_for_status=lambda: None,
        )
        groups = client.fetch_errors("1h")
        assert len(groups[0].message) <= 500


class TestFetchTraces:
    @pytest.fixture
    def client(self):
        with patch("nightwatch.newrelic.httpx.Client") as mock_httpx:
            self.mock_http = mock_httpx.return_value
            nr = NewRelicClient()
            yield nr

    def test_returns_trace_data(self, client):
        tx_errors = [{"error.class": "NoMethodError", "error.message": "nil"}]
        traces = [{"error.message": "nil", "error.stack_trace": "stack..."}]
        self.mock_http.post.return_value = MagicMock(
            json=lambda: make_graphql_response(tx_errors),
            raise_for_status=lambda: None,
        )
        error = make_error_group()
        # Two calls: tx_nrql then trace_nrql
        self.mock_http.post.side_effect = [
            MagicMock(
                json=lambda: make_graphql_response(tx_errors),
                raise_for_status=lambda: None,
            ),
            MagicMock(
                json=lambda: make_graphql_response(traces),
                raise_for_status=lambda: None,
            ),
        ]
        result = client.fetch_traces(error, "24h")
        assert len(result.transaction_errors) == 1
        assert len(result.error_traces) == 1


class TestEscapeNrql:
    def test_escapes_single_quotes(self):
        assert _escape_nrql("it's") == "it\\'s"

    def test_no_change_for_safe_strings(self):
        assert _escape_nrql("NoMethodError") == "NoMethodError"


class TestLoadIgnorePatterns:
    def test_loads_from_yaml(self, tmp_path):
        yml = tmp_path / "ignore.yml"
        yml.write_text("ignore:\n  - pattern: CsrfTokenError\n    match: contains\n")
        patterns = load_ignore_patterns(str(yml))
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "CsrfTokenError"

    def test_missing_file_returns_empty(self, tmp_path):
        patterns = load_ignore_patterns(str(tmp_path / "missing.yml"))
        assert patterns == []

    def test_empty_yaml_returns_empty(self, tmp_path):
        yml = tmp_path / "ignore.yml"
        yml.write_text("")
        patterns = load_ignore_patterns(str(yml))
        assert patterns == []
