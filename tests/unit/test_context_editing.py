"""Tests for Anthropic beta context editing integration (Phase 2).

Verifies that _call_claude_with_retry correctly uses the beta API with
context management when nightwatch_context_editing is enabled, and falls
back to the standard API when disabled.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from nightwatch.analyzer import _call_claude_with_retry
from nightwatch.config import get_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(with_context_mgmt: bool = False):
    """Build a mock Anthropic response with usage stats."""
    resp = MagicMock()
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 500
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0

    if with_context_mgmt:
        edit = MagicMock()
        edit.type = "clear_thinking_20251015"
        edit.cleared_input_tokens = 3200
        resp.context_management.applied_edits = [edit]
    else:
        resp.context_management = None

    return resp


def _make_mock_client(response):
    """Build a mock Anthropic client with both .messages and .beta.messages."""
    client = MagicMock()
    client.messages.create.return_value = response
    client.beta.messages.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Tests: beta API selection
# ---------------------------------------------------------------------------


class TestContextEditingBetaAPISelection:
    """Verify correct API path is chosen based on config."""

    def test_uses_beta_api_when_context_editing_enabled(self, monkeypatch):
        """When nightwatch_context_editing=True, should call client.beta.messages.create."""
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_CONTEXT_EDITING", "true")

        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        client.beta.messages.create.assert_called_once()
        client.messages.create.assert_not_called()

    def test_uses_standard_api_when_context_editing_disabled(self, monkeypatch):
        """When nightwatch_context_editing=False, should call client.messages.create."""
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_CONTEXT_EDITING", "false")

        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        client.messages.create.assert_called_once()
        client.beta.messages.create.assert_not_called()

    def test_default_config_uses_beta_api(self):
        """Default config has context editing enabled — should use beta API."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        client.beta.messages.create.assert_called_once()
        client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: context management parameter structure
# ---------------------------------------------------------------------------


class TestContextManagementParameter:
    """Verify the context_management parameter is correctly structured."""

    def test_context_management_has_both_edit_types(self):
        """context_management should include clear_thinking and clear_tool_uses edits."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.beta.messages.create.call_args
        ctx_mgmt = call_kwargs.kwargs["context_management"]
        edits = ctx_mgmt["edits"]

        assert len(edits) == 2
        assert edits[0]["type"] == "clear_thinking_20251015"
        assert edits[1]["type"] == "clear_tool_uses_20250919"

    def test_clear_thinking_comes_first(self):
        """Per Anthropic API docs, clear_thinking must come before clear_tool_uses."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.beta.messages.create.call_args
        edits = call_kwargs.kwargs["context_management"]["edits"]

        assert edits[0]["type"] == "clear_thinking_20251015"

    def test_clear_thinking_keeps_2_turns(self):
        """clear_thinking should keep the 2 most recent thinking turns."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.beta.messages.create.call_args
        thinking_edit = call_kwargs.kwargs["context_management"]["edits"][0]

        assert thinking_edit["keep"] == {"type": "thinking_turns", "value": 2}

    def test_clear_tool_uses_trigger_and_keep(self):
        """clear_tool_uses should trigger at 30K tokens, keep 4, clear at least 5K."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.beta.messages.create.call_args
        tool_edit = call_kwargs.kwargs["context_management"]["edits"][1]

        assert tool_edit["trigger"] == {"type": "input_tokens", "value": 30000}
        assert tool_edit["keep"] == {"type": "tool_uses", "value": 4}
        assert tool_edit["clear_at_least"] == {"type": "input_tokens", "value": 5000}

    def test_beta_header_included(self):
        """Beta API call should include the context-management beta header."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.beta.messages.create.call_args
        assert "context-management-2025-06-27" in call_kwargs.kwargs["betas"]

    def test_no_context_management_when_disabled(self, monkeypatch):
        """Standard API call should not include context_management."""
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_CONTEXT_EDITING", "false")

        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _call_claude_with_retry(client=client, model="test-model", messages=messages)

        call_kwargs = client.messages.create.call_args
        assert "context_management" not in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# Tests: context management logging
# ---------------------------------------------------------------------------


class TestContextManagementLogging:
    """Verify logging of context editing metrics."""

    def test_logs_cleared_tokens_when_edits_applied(self, caplog):
        """Should log token savings when context edits are applied."""
        response = _make_mock_response(with_context_mgmt=True)
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        with caplog.at_level(logging.INFO, logger="nightwatch.analyzer"):
            _call_claude_with_retry(client=client, model="test-model", messages=messages)

        assert any("Context edit" in record.message for record in caplog.records)
        assert any("cleared 3200 tokens" in record.message for record in caplog.records)

    def test_no_logging_when_no_context_management(self, caplog):
        """Should not log context edits when response has no context_management."""
        response = _make_mock_response(with_context_mgmt=False)
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        with caplog.at_level(logging.INFO, logger="nightwatch.analyzer"):
            _call_claude_with_retry(client=client, model="test-model", messages=messages)

        assert not any("Context edit" in record.message for record in caplog.records)

    def test_logs_multiple_edits(self, caplog):
        """Should log each applied edit separately."""
        response = _make_mock_response(with_context_mgmt=True)

        edit1 = MagicMock()
        edit1.type = "clear_thinking_20251015"
        edit1.cleared_input_tokens = 2000

        edit2 = MagicMock()
        edit2.type = "clear_tool_uses_20250919"
        edit2.cleared_input_tokens = 4500

        response.context_management.applied_edits = [edit1, edit2]
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        with caplog.at_level(logging.INFO, logger="nightwatch.analyzer"):
            _call_claude_with_retry(client=client, model="test-model", messages=messages)

        context_edit_logs = [r for r in caplog.records if "Context edit" in r.message]
        assert len(context_edit_logs) == 2
        assert "cleared 2000 tokens" in context_edit_logs[0].message
        assert "cleared 4500 tokens" in context_edit_logs[1].message


# ---------------------------------------------------------------------------
# Tests: return value
# ---------------------------------------------------------------------------


class TestReturnValue:
    """Verify that return values are consistent regardless of API path."""

    def test_returns_response_and_token_count(self):
        """Should return (response, total_tokens) tuple."""
        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        result_response, tokens = _call_claude_with_retry(
            client=client, model="test-model", messages=messages
        )

        assert result_response is response
        assert tokens == 1500  # 1000 input + 500 output

    def test_returns_same_token_count_with_standard_api(self, monkeypatch):
        """Token calculation should be the same regardless of API path."""
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_CONTEXT_EDITING", "false")

        response = _make_mock_response()
        client = _make_mock_client(response)
        messages = [{"role": "user", "content": "test"}]

        _, tokens = _call_claude_with_retry(client=client, model="test-model", messages=messages)

        assert tokens == 1500
