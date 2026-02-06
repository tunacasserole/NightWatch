"""Tests for nightwatch.analyzer helper functions — pure functions and utilities."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from nightwatch.analyzer import (
    _brief,
    _calculate_max_iterations,
    _calculate_thinking_budget,
    _compress_conversation,
    _evaluate_analysis_quality,
    _execute_single_tool,
    _parse_analysis,
    _serialize_content,
    _truncate_tool_result,
)
from nightwatch.models import TraceData
from tests.factories import make_analysis, make_error_analysis_result, make_file_change


# ---------------------------------------------------------------------------
# _calculate_max_iterations
# ---------------------------------------------------------------------------


class TestCalculateMaxIterations:
    def test_simple_error_caps_at_7(self):
        assert _calculate_max_iterations("NoMethodError", 20) == 7

    def test_auth_error_caps_at_5(self):
        assert _calculate_max_iterations("NotAuthorized", 20) == 5

    def test_db_error_caps_at_10(self):
        assert _calculate_max_iterations("ActiveRecord::StatementInvalid", 20) == 10

    def test_complex_error_caps_at_15(self):
        assert _calculate_max_iterations("SystemStackError", 20) == 15

    def test_unknown_error_defaults_to_10(self):
        assert _calculate_max_iterations("SomeRandomError", 20) == 10

    def test_settings_max_constrains(self):
        # If settings_max is lower than category limit, use settings_max
        assert _calculate_max_iterations("NoMethodError", 3) == 3

    def test_empty_error_class(self):
        assert _calculate_max_iterations("", 20) == 10

    def test_none_error_class(self):
        assert _calculate_max_iterations(None, 20) == 10


# ---------------------------------------------------------------------------
# _calculate_thinking_budget
# ---------------------------------------------------------------------------


class TestCalculateThinkingBudget:
    def test_simple_error_lower_base(self):
        budget = _calculate_thinking_budget(1, 10, "NoMethodError")
        assert budget == 4000  # base for simple, scale=1.0 at iter 1

    def test_complex_error_higher_base(self):
        budget = _calculate_thinking_budget(1, 10, "SystemStackError")
        assert budget == 12000

    def test_unknown_error_medium_base(self):
        budget = _calculate_thinking_budget(1, 10, "SomeError")
        assert budget == 8000

    def test_later_iterations_scale_down(self):
        # At iteration 10 of 10, progress=1.0, scale=0.25
        budget = _calculate_thinking_budget(10, 10, "SomeError")
        assert budget == max(2000, int(8000 * 0.25))

    def test_early_iterations_no_scale(self):
        budget = _calculate_thinking_budget(2, 10, "SomeError")
        assert budget == 8000  # scale=1.0 at iter <= 2

    def test_min_budget_2000(self):
        budget = _calculate_thinking_budget(100, 100, "NoMethodError")
        assert budget >= 2000

    def test_empty_error_class(self):
        budget = _calculate_thinking_budget(1, 10, "")
        assert budget == 8000  # default base


# ---------------------------------------------------------------------------
# _truncate_tool_result
# ---------------------------------------------------------------------------


class TestTruncateToolResult:
    def test_short_result_unchanged(self):
        result = "short text"
        assert _truncate_tool_result(result, max_chars=100) == result

    def test_exact_limit_unchanged(self):
        result = "a" * 100
        assert _truncate_tool_result(result, max_chars=100) == result

    def test_long_result_truncated(self):
        result = "A" * 200
        truncated = _truncate_tool_result(result, max_chars=100)
        assert len(truncated) < 200
        assert "truncated" in truncated
        assert truncated.startswith("A" * 50)
        assert truncated.endswith("A" * 50)

    def test_preserves_beginning_and_end(self):
        result = "START" + "x" * 1000 + "END"
        truncated = _truncate_tool_result(result, max_chars=100)
        assert truncated.startswith("START")
        assert truncated.endswith("END")


# ---------------------------------------------------------------------------
# _serialize_content
# ---------------------------------------------------------------------------


class TestSerializeContent:
    def test_text_block(self):
        block = MagicMock(type="text", text="hello")
        result = _serialize_content([block])
        assert result == [{"type": "text", "text": "hello"}]

    def test_tool_use_block(self):
        block = MagicMock(type="tool_use", id="t1", input={"path": "a.rb"})
        block.configure_mock(name="read_file")
        result = _serialize_content([block])
        assert result == [{"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.rb"}}]

    def test_thinking_block_skipped(self):
        block = MagicMock(type="thinking")
        result = _serialize_content([block])
        assert result == []

    def test_mixed_blocks(self):
        tool_block = MagicMock(type="tool_use", id="t1", input={"query": "q"})
        tool_block.configure_mock(name="search_code")
        blocks = [
            MagicMock(type="thinking"),
            MagicMock(type="text", text="analysis"),
            tool_block,
        ]
        result = _serialize_content(blocks)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "tool_use"


# ---------------------------------------------------------------------------
# _brief
# ---------------------------------------------------------------------------


class TestBrief:
    def test_simple_dict(self):
        result = _brief({"path": "file.rb"})
        assert "path=" in result
        assert "file.rb" in result

    def test_multiple_keys(self):
        result = _brief({"a": 1, "b": "hello"})
        assert "a=" in result
        assert "b=" in result

    def test_long_value_truncated(self):
        result = _brief({"key": "x" * 100})
        # repr is truncated to 40 chars
        assert len(result) < 60

    def test_empty_dict(self):
        assert _brief({}) == ""


# ---------------------------------------------------------------------------
# _evaluate_analysis_quality
# ---------------------------------------------------------------------------


class TestEvaluateAnalysisQuality:
    def test_high_quality_result(self):
        result = make_error_analysis_result()
        result.analysis = make_analysis(
            confidence="high",
            root_cause="A very detailed root cause explanation here that is over twenty characters",
            has_fix=True,
            reasoning="x" * 300,
        )
        result.analysis.file_changes = [make_file_change()]
        result.analysis.suggested_next_steps = ["step1", "step2"]
        score = _evaluate_analysis_quality(result)
        assert score >= 0.8

    def test_low_quality_result(self):
        result = make_error_analysis_result()
        result.analysis = make_analysis(
            confidence="low",
            root_cause="",
            has_fix=False,
            reasoning="short",
        )
        result.analysis.file_changes = []
        result.analysis.suggested_next_steps = []
        score = _evaluate_analysis_quality(result)
        assert score < 0.2

    def test_medium_quality_result(self):
        result = make_error_analysis_result()
        result.analysis = make_analysis(
            confidence="medium",
            root_cause="Some root cause text",
            has_fix=True,
        )
        result.analysis.file_changes = []
        result.analysis.suggested_next_steps = ["step1"]
        score = _evaluate_analysis_quality(result)
        assert 0.3 <= score <= 0.7

    def test_score_capped_at_one(self):
        result = make_error_analysis_result()
        result.analysis = make_analysis(confidence="high")
        score = _evaluate_analysis_quality(result)
        assert score <= 1.0


# ---------------------------------------------------------------------------
# _parse_analysis
# ---------------------------------------------------------------------------


class TestParseAnalysis:
    def test_parses_json_response(self):
        data = {
            "title": "Fix NoMethodError",
            "reasoning": "Missing nil check",
            "root_cause": "nil reference",
            "has_fix": True,
            "confidence": "high",
            "file_changes": [
                {"path": "app/models/product.rb", "action": "modify", "description": "Add guard"}
            ],
            "suggested_next_steps": ["Add tests"],
        }
        block = MagicMock(text=json.dumps(data))
        block.type = "text"
        response = MagicMock(content=[block])
        analysis = _parse_analysis(response)
        assert analysis.title == "Fix NoMethodError"
        assert analysis.has_fix is True
        assert len(analysis.file_changes) == 1

    def test_parses_json_in_markdown(self):
        data = {"title": "Test", "reasoning": "r", "root_cause": "rc", "has_fix": False}
        text = f"Here is my analysis:\n```json\n{json.dumps(data)}\n```"
        block = MagicMock(text=text)
        block.type = "text"
        response = MagicMock(content=[block])
        analysis = _parse_analysis(response)
        assert analysis.title == "Test"

    def test_falls_back_on_invalid_json(self):
        block = MagicMock(text="This is not JSON at all, just text analysis.")
        block.type = "text"
        response = MagicMock(content=[block])
        analysis = _parse_analysis(response)
        assert analysis.title == "Analysis Complete"
        assert analysis.has_fix is False
        assert "not JSON" in analysis.reasoning

    def test_handles_empty_content(self):
        response = MagicMock(content=[])
        analysis = _parse_analysis(response)
        assert analysis.title == "Analysis Complete"


# ---------------------------------------------------------------------------
# _compress_conversation
# ---------------------------------------------------------------------------


class TestCompressConversation:
    def test_short_conversation_unchanged(self):
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
        result = _compress_conversation(messages)
        assert result == messages

    def test_exactly_six_unchanged(self):
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(6)]
        result = _compress_conversation(messages)
        assert result == messages

    def test_long_conversation_compressed(self):
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = _compress_conversation(messages)
        assert len(result) == 6  # first + compressed + last 4
        assert result[0] == messages[0]
        assert "COMPRESSED" in result[1]["content"]
        assert result[-1] == messages[-1]

    def test_extracts_tool_calls_from_middle(self):
        messages = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "read_file", "input": {"path": "a.rb"}},
            ]},
            {"role": "user", "content": "mid1"},
            {"role": "assistant", "content": "mid2"},
            {"role": "user", "content": "mid3"},
            {"role": "assistant", "content": "mid4"},
            {"role": "user", "content": "end1"},
            {"role": "assistant", "content": "end2"},
            {"role": "user", "content": "end3"},
            {"role": "assistant", "content": "end4"},
        ]
        result = _compress_conversation(messages)
        compressed_msg = result[1]["content"]
        assert "read_file" in compressed_msg


# ---------------------------------------------------------------------------
# _execute_single_tool
# ---------------------------------------------------------------------------


class TestExecuteSingleTool:
    def _call(self, tool_name, tool_input, traces=None, gh=None, nr=None):
        error = MagicMock()
        if traces is None:
            traces = TraceData(transaction_errors=[], error_traces=[])
        if gh is None:
            gh = MagicMock()
        if nr is None:
            nr = MagicMock()
        return _execute_single_tool(tool_name, tool_input, error, traces, gh, nr)

    def test_read_file(self):
        gh = MagicMock()
        gh.read_file.return_value = "class Product\nend"
        result = self._call("read_file", {"path": "app/models/product.rb"}, gh=gh)
        assert "class Product" in result

    def test_read_file_not_found(self):
        gh = MagicMock()
        gh.read_file.return_value = None
        result = self._call("read_file", {"path": "missing.rb"}, gh=gh)
        assert "File not found" in result

    def test_search_code(self):
        gh = MagicMock()
        gh.search_code.return_value = [{"path": "a.rb", "name": "a.rb"}]
        result = self._call("search_code", {"query": "Product"}, gh=gh)
        assert "a.rb" in result

    def test_search_code_no_results(self):
        gh = MagicMock()
        gh.search_code.return_value = []
        result = self._call("search_code", {"query": "nothing"}, gh=gh)
        assert "No matches found" in result

    def test_list_directory(self):
        gh = MagicMock()
        gh.list_directory.return_value = [{"name": "product.rb", "type": "file"}]
        result = self._call("list_directory", {"path": "app/models"}, gh=gh)
        assert "product.rb" in result

    def test_list_directory_not_found(self):
        gh = MagicMock()
        gh.list_directory.return_value = []
        result = self._call("list_directory", {"path": "nonexistent"}, gh=gh)
        assert "Directory not found" in result

    def test_get_error_traces(self):
        traces = TraceData(
            transaction_errors=[{"error.class": "NoMethodError"}],
            error_traces=[{"error.message": "nil"}],
        )
        result = self._call("get_error_traces", {}, traces=traces)
        assert "NoMethodError" in result

    def test_unknown_tool(self):
        result = self._call("unknown_tool", {})
        assert "Unknown tool" in result
