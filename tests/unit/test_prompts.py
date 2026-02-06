"""Tests for nightwatch.prompts — prompt building, trace summarization, tool definitions."""

from __future__ import annotations

import pytest

from nightwatch.models import PriorAnalysis
from nightwatch.prompts import SYSTEM_PROMPT, TOOLS, build_analysis_prompt, summarize_traces
from tests.factories import make_correlated_pr


class TestSystemPrompt:
    def test_contains_key_instructions(self):
        assert "NightWatch" in SYSTEM_PROMPT
        assert "search_code" in SYSTEM_PROMPT
        assert "read_file" in SYSTEM_PROMPT
        assert "Ruby on Rails" in SYSTEM_PROMPT

    def test_mentions_investigation_steps(self):
        assert "Investigation steps" in SYSTEM_PROMPT
        assert "transactionName" in SYSTEM_PROMPT


class TestTools:
    def test_has_four_tools(self):
        assert len(TOOLS) == 4

    def test_read_file_tool(self):
        tool = next(t for t in TOOLS if t["name"] == "read_file")
        assert "path" in tool["input_schema"]["properties"]
        assert "path" in tool["input_schema"]["required"]

    def test_search_code_tool(self):
        tool = next(t for t in TOOLS if t["name"] == "search_code")
        assert "query" in tool["input_schema"]["properties"]
        assert "file_extension" in tool["input_schema"]["properties"]

    def test_list_directory_tool(self):
        tool = next(t for t in TOOLS if t["name"] == "list_directory")
        assert "path" in tool["input_schema"]["properties"]

    def test_get_error_traces_tool(self):
        tool = next(t for t in TOOLS if t["name"] == "get_error_traces")
        assert "limit" in tool["input_schema"]["properties"]


class TestBuildAnalysisPrompt:
    def test_basic_prompt(self):
        prompt = build_analysis_prompt(
            error_class="NoMethodError",
            transaction="Controller/products/show",
            message="nil error",
            occurrences=42,
            trace_summary="stack trace here",
        )
        assert "NoMethodError" in prompt
        assert "Controller/products/show" in prompt
        assert "nil error" in prompt
        assert "42" in prompt
        assert "stack trace here" in prompt

    def test_truncates_long_message(self):
        prompt = build_analysis_prompt(
            error_class="E",
            transaction="T",
            message="x" * 1000,
            occurrences=1,
            trace_summary="",
        )
        # Message should be truncated to 500 chars in the prompt
        assert len(prompt) < 2000

    def test_includes_prior_analyses(self):
        prior = PriorAnalysis(
            error_class="NoMethodError",
            transaction="Controller/products/show",
            root_cause="Missing nil check",
            fix_confidence="high",
            has_fix=True,
            summary="Fixed by adding guard clause",
            match_score=0.85,
            source_file="knowledge/errors/nomethoderror.md",
            first_detected="2025-01-01",
        )
        prompt = build_analysis_prompt(
            error_class="NoMethodError",
            transaction="Controller/products/show",
            message="nil",
            occurrences=10,
            trace_summary="",
            prior_analyses=[prior],
        )
        assert "Prior Knowledge" in prompt
        assert "85%" in prompt
        assert "Missing nil check" in prompt

    def test_includes_research_context_files(self):
        research = type("ResearchContext", (), {
            "file_previews": {"app/models/product.rb": "class Product\nend"},
            "correlated_prs": [],
        })()
        prompt = build_analysis_prompt(
            error_class="E",
            transaction="T",
            message="m",
            occurrences=1,
            trace_summary="",
            research_context=research,
        )
        assert "Pre-Fetched Source Files" in prompt
        assert "product.rb" in prompt

    def test_includes_research_context_prs(self):
        pr = make_correlated_pr(number=50, title="Fix products", overlap_score=0.8)
        research = type("ResearchContext", (), {
            "file_previews": {},
            "correlated_prs": [pr],
        })()
        prompt = build_analysis_prompt(
            error_class="E",
            transaction="T",
            message="m",
            occurrences=1,
            trace_summary="",
            research_context=research,
        )
        assert "Recently Merged PRs" in prompt
        assert "PR #50" in prompt

    def test_no_prior_or_research(self):
        prompt = build_analysis_prompt(
            error_class="E",
            transaction="T",
            message="m",
            occurrences=1,
            trace_summary="",
        )
        assert "Prior Knowledge" not in prompt
        assert "Pre-Fetched" not in prompt


class TestSummarizeTraces:
    def test_basic_summary(self):
        traces = {
            "transaction_errors": [
                {
                    "error.class": "NoMethodError",
                    "error.message": "nil error",
                    "transactionName": "Controller/products/show",
                    "path": "/products/42",
                    "host": "web-1",
                }
            ],
            "error_traces": [
                {
                    "error.message": "nil error",
                    "error.stack_trace": "app/controllers/products_controller.rb:15",
                }
            ],
        }
        result = summarize_traces(traces)
        assert "Transaction Errors" in result
        assert "NoMethodError" in result
        assert "Stack Traces" in result

    def test_empty_traces(self):
        result = summarize_traces({})
        assert result == "No trace data available."

    def test_truncates_long_stack_trace(self):
        traces = {
            "transaction_errors": [],
            "error_traces": [
                {
                    "error.message": "err",
                    "error.stack_trace": "x" * 1000,
                }
            ],
        }
        result = summarize_traces(traces)
        assert "..." in result

    def test_respects_max_errors(self):
        traces = {
            "transaction_errors": [
                {"error.class": f"Error{i}", "error.message": f"msg{i}"}
                for i in range(10)
            ],
            "error_traces": [],
        }
        result = summarize_traces(traces, max_errors=2)
        assert "Error0" in result
        assert "Error1" in result
        assert "Error2" not in result

    def test_handles_alternative_stack_trace_key(self):
        traces = {
            "transaction_errors": [],
            "error_traces": [
                {
                    "message": "alt err",
                    "stackTrace": "alt stack trace",
                }
            ],
        }
        result = summarize_traces(traces)
        assert "alt stack trace" in result
