"""Shared pytest fixtures for NightWatch test suite."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nightwatch.config import get_settings
from nightwatch.models import (
    ErrorAnalysisResult,
    TraceData,
)

# ---------------------------------------------------------------------------
# Environment isolation — no real .env ever loaded in tests
# ---------------------------------------------------------------------------

_REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "GITHUB_TOKEN": "test-github-token",
    "GITHUB_REPO": "test-org/test-repo",
    "NEW_RELIC_API_KEY": "test-nr-key",
    "NEW_RELIC_ACCOUNT_ID": "12345",
    "NEW_RELIC_APP_NAME": "TestApp",
    "SLACK_BOT_TOKEN": "xoxb-test-token",
    "SLACK_NOTIFY_USER": "testuser",
}


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Every test gets isolated settings with no real env leakage."""
    # Clear cached settings singleton
    get_settings.cache_clear()

    # Set required env vars
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    # Prevent reading real .env file
    monkeypatch.setenv("ENV_FILE", "/dev/null")

    yield

    # Clear again after test
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_error():
    """Factory for ErrorGroup instances."""
    from tests.factories import make_error_group

    return make_error_group


@pytest.fixture
def make_analysis():
    """Factory for Analysis instances."""
    from tests.factories import make_analysis

    return make_analysis


@pytest.fixture
def make_result():
    """Factory for ErrorAnalysisResult instances."""
    from tests.factories import make_error_analysis_result

    return make_error_analysis_result


@pytest.fixture
def make_report():
    """Factory for RunReport instances."""
    from tests.factories import make_run_report

    return make_run_report


# ---------------------------------------------------------------------------
# Common model instances
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_error():
    from tests.factories import make_error_group

    return make_error_group()


@pytest.fixture
def sample_analysis():
    from tests.factories import make_analysis

    return make_analysis()


@pytest.fixture
def sample_traces():
    return TraceData(
        transaction_errors=[
            {
                "error.class": "NoMethodError",
                "error.message": "undefined method `name' for nil",
                "transactionName": "Controller/products/show",
                "path": "/products/42",
                "host": "web-1",
            }
        ],
        error_traces=[
            {
                "error.message": "undefined method `name' for nil",
                "error.stack_trace": (
                    "app/controllers/products_controller.rb:15:in `show'\n"
                    "app/models/product.rb:42:in `display_name'"
                ),
            }
        ],
    )


@pytest.fixture
def sample_result(sample_error, sample_analysis, sample_traces):
    return ErrorAnalysisResult(
        error=sample_error,
        analysis=sample_analysis,
        traces=sample_traces,
        iterations=5,
        tokens_used=8000,
        api_calls=12,
    )


# ---------------------------------------------------------------------------
# Mock client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_github_client():
    """A fully mocked GitHubClient — no real API calls."""
    with patch("nightwatch.github.Github") as mock_gh:
        mock_repo = MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        from nightwatch.github import GitHubClient

        client = GitHubClient()
        client._repo = mock_repo
        yield client


@pytest.fixture
def mock_nr_responses():
    """Factory for crafting mock New Relic NRQL responses."""

    def _make_nrql_response(results):
        return {
            "data": {
                "actor": {
                    "account": {
                        "nrql": {
                            "results": results,
                        }
                    }
                }
            }
        }

    return _make_nrql_response


@pytest.fixture
def mock_slack_client():
    """A fully mocked SlackClient."""
    with patch("nightwatch.slack.WebClient") as mock_web:
        mock_instance = MagicMock()
        mock_web.return_value = mock_instance
        yield mock_instance
