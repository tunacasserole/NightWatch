"""Tests for nightwatch.slack — SlackClient, Block Kit builders, user lookup, DMs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from nightwatch.slack import (
    SlackClient,
    _build_followup_blocks,
    _build_report_blocks,
)
from tests.factories import (
    make_created_issue_result,
    make_created_pr_result,
    make_detected_pattern,
    make_ignore_suggestion,
    make_run_report,
)

# ---------------------------------------------------------------------------
# SlackClient
# ---------------------------------------------------------------------------


class TestSlackClientInit:
    def test_creates_webclient(self):
        with patch("nightwatch.slack.WebClient") as mock_web:
            client = SlackClient()
            mock_web.assert_called_once()
            assert client.notify_user == "testuser"


class TestGetUserId:
    @pytest.fixture
    def slack(self):
        with patch("nightwatch.slack.WebClient") as mock_web:
            self.mock_client = mock_web.return_value
            yield SlackClient()

    def test_finds_by_display_name(self, slack):
        self.mock_client.users_list.return_value = {
            "ok": True,
            "members": [
                {
                    "id": "U123",
                    "name": "testuser",
                    "real_name": "Test User",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {"display_name": "testuser", "real_name": "Test User"},
                },
            ],
        }
        uid = slack._get_user_id("testuser")
        assert uid == "U123"

    def test_caches_result(self, slack):
        self.mock_client.users_list.return_value = {
            "ok": True,
            "members": [
                {
                    "id": "U123",
                    "name": "testuser",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {"display_name": "testuser", "real_name": ""},
                },
            ],
        }
        slack._get_user_id("testuser")
        slack._get_user_id("testuser")  # Should hit cache
        assert self.mock_client.users_list.call_count == 1

    def test_skips_bots_and_deleted(self, slack):
        self.mock_client.users_list.return_value = {
            "ok": True,
            "members": [
                {"id": "B1", "name": "testuser", "deleted": False, "is_bot": True, "profile": {}},
                {"id": "D1", "name": "testuser", "deleted": True, "is_bot": False, "profile": {}},
            ],
        }
        assert slack._get_user_id("testuser") is None

    def test_not_found_returns_none(self, slack):
        self.mock_client.users_list.return_value = {
            "ok": True,
            "members": [
                {
                    "id": "U999",
                    "name": "otheruser",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {"display_name": "otheruser", "real_name": "Other"},
                },
            ],
        }
        assert slack._get_user_id("testuser") is None

    def test_api_error_returns_none(self, slack):
        self.mock_client.users_list.side_effect = SlackApiError(
            message="error", response=MagicMock(data={})
        )
        assert slack._get_user_id("testuser") is None

    def test_fuzzy_partial_match(self, slack):
        self.mock_client.users_list.return_value = {
            "ok": True,
            "members": [
                {
                    "id": "U456",
                    "name": "alice.henderson",
                    "real_name": "Alice Henderson",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {"display_name": "alice.henderson", "real_name": "Alice Henderson"},
                },
            ],
        }
        # Fuzzy: "alice" is substring of "alice.henderson"
        uid = slack._get_user_id("alice")
        assert uid == "U456"


class TestOpenDm:
    @pytest.fixture
    def slack(self):
        with patch("nightwatch.slack.WebClient") as mock_web:
            self.mock_client = mock_web.return_value
            yield SlackClient()

    def test_returns_channel_id(self, slack):
        self.mock_client.conversations_open.return_value = {
            "ok": True,
            "channel": {"id": "D123"},
        }
        assert slack._open_dm("U123") == "D123"

    def test_api_error_returns_none(self, slack):
        self.mock_client.conversations_open.side_effect = SlackApiError(
            message="error", response=MagicMock(data={})
        )
        assert slack._open_dm("U123") is None


class TestSendReport:
    @pytest.fixture
    def slack(self):
        with patch("nightwatch.slack.WebClient") as mock_web:
            self.mock_client = mock_web.return_value
            s = SlackClient()
            # Set up successful user lookup and DM open
            self.mock_client.users_list.return_value = {
                "ok": True,
                "members": [
                    {
                        "id": "U123",
                        "name": "testuser",
                        "deleted": False,
                        "is_bot": False,
                        "profile": {"display_name": "testuser", "real_name": ""},
                    }
                ],
            }
            self.mock_client.conversations_open.return_value = {
                "ok": True,
                "channel": {"id": "D123"},
            }
            yield s

    def test_sends_report(self, slack):
        report = make_run_report()
        assert slack.send_report(report) is True
        self.mock_client.chat_postMessage.assert_called_once()
        call_kwargs = self.mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "D123"
        assert "NightWatch" in call_kwargs["text"]

    def test_returns_false_on_send_error(self, slack):
        self.mock_client.chat_postMessage.side_effect = SlackApiError(
            message="error", response=MagicMock(data={})
        )
        report = make_run_report()
        assert slack.send_report(report) is False


class TestSendFollowup:
    @pytest.fixture
    def slack(self):
        with patch("nightwatch.slack.WebClient") as mock_web:
            self.mock_client = mock_web.return_value
            s = SlackClient()
            self.mock_client.users_list.return_value = {
                "ok": True,
                "members": [
                    {
                        "id": "U123",
                        "name": "testuser",
                        "deleted": False,
                        "is_bot": False,
                        "profile": {"display_name": "testuser", "real_name": ""},
                    }
                ],
            }
            self.mock_client.conversations_open.return_value = {
                "ok": True,
                "channel": {"id": "D123"},
            }
            yield s

    def test_sends_followup_with_issues_and_pr(self, slack):
        issues = [make_created_issue_result()]
        pr = make_created_pr_result()
        assert slack.send_followup(issues, pr) is True
        self.mock_client.chat_postMessage.assert_called_once()

    def test_sends_followup_without_pr(self, slack):
        issues = [make_created_issue_result()]
        assert slack.send_followup(issues, None) is True


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------


class TestBuildReportBlocks:
    def test_basic_report(self):
        report = make_run_report()
        blocks = _build_report_blocks(report)
        # Header, stats section, divider, per-error section, footer divider, footer context
        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "section"  # stats
        assert any(b["type"] == "context" for b in blocks)  # footer

    def test_includes_multi_pass_retry_field(self):
        report = make_run_report(multi_pass_retries=2)
        blocks = _build_report_blocks(report)
        stats_block = blocks[1]
        field_texts = [f["text"] for f in stats_block["fields"]]
        assert any("Retried" in t for t in field_texts)

    def test_includes_patterns_section(self):
        pattern = make_detected_pattern()
        report = make_run_report(patterns=[pattern])
        blocks = _build_report_blocks(report)
        texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
        assert any("Patterns" in t for t in texts)

    def test_includes_ignore_suggestions(self):
        suggestion = make_ignore_suggestion()
        report = make_run_report(ignore_suggestions=[suggestion])
        blocks = _build_report_blocks(report)
        texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
        assert any("Ignore Suggestions" in t for t in texts)


class TestBuildFollowupBlocks:
    def test_with_issues_and_pr(self):
        issues = [make_created_issue_result()]
        pr = make_created_pr_result()
        blocks = _build_followup_blocks(issues, pr)
        assert blocks[0]["type"] == "header"
        texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
        assert any("Created" in t for t in texts)
        assert any("Draft PR" in t for t in texts)

    def test_with_commented_issue(self):
        issue = make_created_issue_result(action="commented")
        blocks = _build_followup_blocks([issue], None)
        texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
        assert any("Updated" in t for t in texts)

    def test_without_pr(self):
        issues = [make_created_issue_result()]
        blocks = _build_followup_blocks(issues, None)
        texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
        assert not any("Draft PR" in t for t in texts)
