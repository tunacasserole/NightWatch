"""Claude agentic analysis loop — multi-pass with prompt caching.

Implements the Ralph pattern: fresh context per pass with seed knowledge
from prior passes. Low-confidence results get a retry with enriched context.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import anthropic

from nightwatch.config import get_settings
from nightwatch.models import (
    Analysis,
    Confidence,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    RunContext,
    TraceData,
)
from nightwatch.observability import wrap_anthropic_client
from nightwatch.prompts import SYSTEM_PROMPT, TOOLS, build_analysis_prompt, summarize_traces

logger = logging.getLogger("nightwatch.analyzer")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    run_context: RunContext | None = None,
    prior_analyses: list | None = None,
    research_context: Any | None = None,
    agent_name: str = "base-analyzer",
    prior_context: str | None = None,
) -> ErrorAnalysisResult:
    """Run Claude's agentic loop to analyze a single error, with optional multi-pass retry.

    If the first pass returns confidence='low' and multi-pass is enabled,
    a second pass is attempted with the first pass's findings as seed context.
    This implements the Ralph pattern: fresh context per iteration with
    accumulated knowledge.

    Args:
        error: The error group to analyze.
        traces: Pre-fetched trace data for this error.
        github_client: GitHubClient instance (provides read_file, search_code, list_directory).
        newrelic_client: NewRelicClient instance (provides fetch_traces).
        run_context: Optional accumulated run context for cross-error knowledge sharing.
        prior_analyses: Optional prior analyses from knowledge base (Phase 1).
        research_context: Optional pre-gathered research context (Phase 2).
        agent_name: Agent definition to use for analysis (Phase 3).

    Returns:
        ErrorAnalysisResult with the best analysis result across passes.
    """
    settings = get_settings()

    # Build seed from run_context + prior_context if available
    context_seed: str | None = None
    if run_context and settings.nightwatch_run_context_enabled:
        context_section = run_context.to_prompt_section(settings.nightwatch_run_context_max_chars)
        if context_section:
            context_seed = context_section
    if prior_context:
        context_seed = f"{context_seed}\n\n{prior_context}" if context_seed else prior_context

    # Pass 1
    result = _single_pass(
        error=error,
        traces=traces,
        github_client=github_client,
        newrelic_client=newrelic_client,
        seed_context=context_seed,
        prior_analyses=prior_analyses,
        research_context=research_context,
        agent_name=agent_name,
    )

    # Multi-pass retry logic
    if (
        settings.nightwatch_multi_pass_enabled
        and result.analysis.confidence == Confidence.LOW
        and settings.nightwatch_max_passes > 1
    ):
        logger.info(
            f"  Pass 1 returned LOW confidence — retrying with seed knowledge "
            f"(pass 2/{settings.nightwatch_max_passes})"
        )

        # Build seed from pass 1 findings + run context
        retry_seed = _build_retry_seed(result)
        if context_seed:
            retry_seed = f"{retry_seed}\n\n{context_seed}"

        pass1_result = result
        result = _single_pass(
            error=error,
            traces=traces,
            github_client=github_client,
            newrelic_client=newrelic_client,
            seed_context=retry_seed,
            prior_analyses=prior_analyses,
            research_context=research_context,
            agent_name=agent_name,
        )

        # Accumulate totals from both passes
        result.tokens_used += pass1_result.tokens_used
        result.api_calls += pass1_result.api_calls
        result.iterations += pass1_result.iterations
        result.pass_count = 2

        # Use pass 2 result only if it improved confidence
        if _confidence_rank(result.analysis.confidence) < _confidence_rank(
            pass1_result.analysis.confidence
        ):
            # Pass 2 didn't improve — keep pass 1's analysis but record the extra cost
            result.analysis = pass1_result.analysis

    # Record to run context
    if run_context and settings.nightwatch_run_context_enabled:
        run_context.record_analysis(
            error_class=error.error_class,
            transaction=error.transaction,
            summary=result.analysis.root_cause[:200] if result.analysis.root_cause else "",
        )

    return result


# ---------------------------------------------------------------------------
# Context efficiency: adaptive iteration limits and thinking budgets
# ---------------------------------------------------------------------------

_SIMPLE_ERRORS = [
    "nomethoderror", "nameerror", "argumenterror",
    "typeerror", "keyerror", "attributeerror",
]
_AUTH_ERRORS = ["notauthorized", "forbidden", "authentication", "unauthorized"]
_DB_ERRORS = ["activerecord", "pg::", "statementinvalid", "deadlock", "mysql"]
_COMPLEX_ERRORS = ["systemstackerror", "timeout", "connectionerror", "nomemoryerror", "segfault"]


def _calculate_max_iterations(error_class: str, settings_max: int) -> int:
    """Calculate max iterations based on error type complexity."""
    ec = error_class.lower() if error_class else ""
    if any(p in ec for p in _SIMPLE_ERRORS):
        return min(7, settings_max)
    if any(p in ec for p in _AUTH_ERRORS):
        return min(5, settings_max)
    if any(p in ec for p in _DB_ERRORS):
        return min(10, settings_max)
    if any(p in ec for p in _COMPLEX_ERRORS):
        return min(15, settings_max)
    return min(10, settings_max)


def _calculate_thinking_budget(iteration: int, max_iterations: int, error_class: str) -> int:
    """Calculate thinking token budget based on iteration and error complexity."""
    ec = error_class.lower() if error_class else ""
    if any(p in ec for p in _SIMPLE_ERRORS):
        base = 4000
    elif any(p in ec for p in _COMPLEX_ERRORS):
        base = 12000
    else:
        base = 8000
    if iteration <= 2 or max_iterations <= 2:
        scale = 1.0
    else:
        progress = (iteration - 2) / (max_iterations - 2)
        scale = 1.0 - (0.75 * progress)
    return max(2000, int(base * scale))


# ---------------------------------------------------------------------------
# Context efficiency: tool result truncation
# ---------------------------------------------------------------------------

TOOL_RESULT_LIMITS = {
    "read_file": 8000,
    "search_code": 4000,
    "list_directory": 2000,
    "get_error_traces": 4000,
}


def _truncate_tool_result(result: str, max_chars: int = 8000) -> str:
    """Truncate long tool results while preserving beginning and end."""
    if len(result) <= max_chars:
        return result
    half = max_chars // 2
    return (
        result[:half]
        + f"\n\n[... {len(result) - max_chars} chars truncated ...]\n\n"
        + result[-half:]
    )


# ---------------------------------------------------------------------------
# Single-pass analysis (extracted from original analyze_error)
# ---------------------------------------------------------------------------


def _single_pass(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    seed_context: str | None = None,
    prior_analyses: list | None = None,
    research_context: Any | None = None,
    agent_name: str = "base-analyzer",
) -> ErrorAnalysisResult:
    """Run a single Claude agentic loop to analyze an error.

    This is the original analyze_error() body, extracted so the public
    analyze_error() can orchestrate multiple passes.

    Args:
        error: The error group to analyze.
        traces: Pre-fetched trace data for this error.
        github_client: GitHubClient instance.
        newrelic_client: NewRelicClient instance.
        seed_context: Optional context to prepend (from prior pass or run context).
        prior_analyses: Optional prior analyses from knowledge base.
        research_context: Optional pre-gathered research context.
        agent_name: Agent definition to use.

    Returns:
        ErrorAnalysisResult with the analysis, iteration count, and token usage.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    client = wrap_anthropic_client(client)

    # Build initial prompt
    trace_summary = summarize_traces(
        {"transaction_errors": traces.transaction_errors, "error_traces": traces.error_traces}
    )
    initial_message = build_analysis_prompt(
        error_class=error.error_class,
        transaction=error.transaction,
        message=error.message,
        occurrences=error.occurrences,
        trace_summary=trace_summary,
        prior_analyses=prior_analyses,
        research_context=research_context,
    )

    if seed_context:
        initial_message += f"\n\n{seed_context}"

    messages: list[dict] = [{"role": "user", "content": initial_message}]

    iteration = 0
    max_iterations = _calculate_max_iterations(
        error.error_class, settings.nightwatch_max_iterations
    )
    logger.info(
        f"  Error class {error.error_class} → max_iterations={max_iterations} "
        f"(ceiling: {settings.nightwatch_max_iterations})"
    )
    total_tokens = 0
    api_calls = 0
    token_budget = getattr(settings, "nightwatch_token_budget_per_error", 30000)

    while iteration < max_iterations:
        iteration += 1
        if iteration > 1:
            time.sleep(1.5)  # Rate-limit protection

        # Adaptive thinking budget
        thinking_budget = _calculate_thinking_budget(
            iteration, max_iterations, error.error_class
        )
        logger.info(f"  Iteration {iteration}/{max_iterations} (thinking: {thinking_budget})")

        # Token budget enforcement
        if total_tokens > token_budget:
            logger.warning(
                f"  Token budget {total_tokens}/{token_budget} — forcing wrap-up"
            )
            break

        response, tokens = _call_claude_with_retry(
            client=client,
            model=settings.nightwatch_model,
            messages=messages,
            thinking_budget=thinking_budget,
        )
        total_tokens += tokens
        api_calls += 1

        if response.stop_reason == "tool_use":
            tool_results = _execute_tools(
                response.content, error, traces, github_client, newrelic_client
            )
            messages.append({
                "role": "assistant",
                "content": _serialize_content(response.content),
            })
            messages.append({"role": "user", "content": tool_results})

            # Compress conversation if getting long
            if iteration > 6 and len(messages) > 8:
                messages = _compress_conversation(messages)
        else:
            # Claude is done — parse structured output
            analysis = _parse_analysis(response)
            logger.info(
                f"  Analysis complete — {iteration} iterations, "
                f"{total_tokens} tokens, has_fix={analysis.has_fix}"
            )
            return ErrorAnalysisResult(
                error=error,
                analysis=analysis,
                traces=traces,
                iterations=iteration,
                tokens_used=total_tokens,
                api_calls=api_calls,
            )

    # Hit max iterations
    logger.warning(f"  Hit max iterations ({max_iterations})")
    return ErrorAnalysisResult(
        error=error,
        analysis=Analysis(
            title=f"{error.error_class} in {error.transaction}",
            reasoning="Analysis incomplete — hit iteration limit",
            root_cause="Unknown — analysis did not complete",
            has_fix=False,
            confidence="low",
            suggested_next_steps=["Manual investigation required"],
        ),
        traces=traces,
        iterations=iteration,
        tokens_used=total_tokens,
        api_calls=api_calls,
    )


# ---------------------------------------------------------------------------
# Multi-pass helpers
# ---------------------------------------------------------------------------


def _build_retry_seed(result: ErrorAnalysisResult) -> str:
    """Build seed context from a completed pass for retry.

    Extracts the key findings from pass 1 so pass 2 starts with
    prior knowledge without the full conversation history.
    """
    parts = [
        "## Previous Analysis Attempt (Confidence: LOW)",
        f"**Root cause hypothesis**: {result.analysis.root_cause}",
        f"**Reasoning so far**: {result.analysis.reasoning[:500]}",
    ]
    if result.analysis.file_changes:
        files = ", ".join(fc.path for fc in result.analysis.file_changes[:5])
        parts.append(f"**Files examined**: {files}")
    if result.analysis.suggested_next_steps:
        steps = "; ".join(result.analysis.suggested_next_steps[:3])
        parts.append(f"**Suggested next steps**: {steps}")
    parts.append(
        "\nThis analysis had LOW confidence. Please investigate more deeply, "
        "using different search strategies or examining additional code paths."
    )
    return "\n".join(parts)


def _confidence_rank(confidence: str | Confidence) -> int:
    """Convert confidence level to numeric rank for comparison."""
    ranks = {"low": 0, "medium": 1, "high": 2}
    return ranks.get(str(confidence).lower(), 0)


# ---------------------------------------------------------------------------
# Claude API call with retry + prompt caching
# ---------------------------------------------------------------------------


def _call_claude_with_retry(
    client: anthropic.Anthropic,
    model: str,
    messages: list[dict],
    max_retries: int = 5,
    base_delay: float = 15.0,
    thinking_budget: int = 8000,
) -> tuple[Any, int]:
    """Call Claude with retry logic and prompt caching.

    Returns (response, total_tokens_used).
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16384,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=TOOLS,
                messages=messages,
                thinking={
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                },
            )

            input_tokens = getattr(response.usage, "input_tokens", 0)
            output_tokens = getattr(response.usage, "output_tokens", 0)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            cache_create = getattr(response.usage, "cache_creation_input_tokens", 0)

            if cache_read:
                logger.debug(f"  Cache hit: {cache_read} tokens read from cache")
            if cache_create:
                logger.debug(f"  Cache write: {cache_create} tokens cached")

            return response, input_tokens + output_tokens

        except anthropic.APIStatusError as e:
            last_error = e
            if e.status_code in (429, 529):
                # Check for retry-after header
                retry_after = getattr(
                    getattr(e, "response", None), "headers", {}
                ).get("retry-after")
                if retry_after:
                    delay = float(retry_after) + random.uniform(1, 5)
                else:
                    delay = min(base_delay * (2**attempt), 120)
                    delay += random.uniform(1, 5)  # jitter
                logger.warning(
                    f"  Rate limited ({e.status_code}), "
                    f"retrying in {delay:.0f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
            elif e.status_code == 400 and "credit balance" in str(e.message).lower():
                logger.warning("  Credit balance low, retrying in 1s")
                time.sleep(1.0)
            else:
                raise

        except anthropic.APIConnectionError as e:
            last_error = e
            delay = base_delay * (2**attempt)
            logger.warning(
                f"  Connection error, retrying in {delay:.0f}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(delay)

    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def _execute_tools(
    content: list[Any],
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
) -> list[dict]:
    """Execute all tool calls in a response and return results."""
    results: list[dict] = []

    for block in content:
        if block.type != "tool_use":
            continue

        tool_name = block.name
        tool_input = block.input
        logger.info(f"    Tool: {tool_name}({_brief(tool_input)})")

        try:
            result = _execute_single_tool(
                tool_name, tool_input, error, traces, github_client, newrelic_client
            )
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
        except Exception as e:
            logger.error(f"    Tool error: {e}")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": f"Error: {e}",
                "is_error": True,
            })

    return results


def _execute_single_tool(
    tool_name: str,
    tool_input: dict,
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
) -> str:
    """Execute a single tool and return the result string."""
    limit = TOOL_RESULT_LIMITS.get(tool_name, 8000)

    if tool_name == "read_file":
        content = github_client.read_file(tool_input["path"])
        result = content if content is not None else f"File not found: {tool_input['path']}"
        return _truncate_tool_result(result, limit)

    if tool_name == "search_code":
        results = github_client.search_code(
            tool_input["query"], tool_input.get("file_extension")
        )
        result = json.dumps(results, indent=2) if results else "No matches found"
        return _truncate_tool_result(result, limit)

    if tool_name == "list_directory":
        contents = github_client.list_directory(tool_input["path"])
        if contents:
            return _truncate_tool_result(json.dumps(contents, indent=2), limit)
        return f"Directory not found: {tool_input['path']}"

    if tool_name == "get_error_traces":
        trace_data = {
            "transaction_errors": traces.transaction_errors,
            "error_traces": traces.error_traces,
        }
        return _truncate_tool_result(json.dumps(trace_data, indent=2), limit)

    return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_analysis(response: Any) -> Analysis:
    """Parse Claude's structured output into an Analysis model.

    With structured outputs (output_config), Claude returns JSON directly.
    Falls back to regex/JSON extraction from text if needed.
    """
    # Extract text content from response
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # Try structured JSON parsing
    try:
        # Look for JSON block in markdown
        json_start = text.find("```json")
        json_end = text.find("```", json_start + 7) if json_start != -1 else -1

        if json_start != -1 and json_end != -1:
            json_str = text[json_start + 7 : json_end].strip()
            data = json.loads(json_str)
        else:
            data = json.loads(text)

        file_changes = [
            FileChange(
                path=fc["path"],
                action=fc.get("action", "modify"),
                content=fc.get("content"),
                description=fc.get("description", ""),
            )
            for fc in data.get("file_changes", [])
        ]

        return Analysis(
            title=data.get("title", "Unknown Error"),
            reasoning=data.get("reasoning", text),
            root_cause=data.get("root_cause", ""),
            has_fix=data.get("has_fix", False),
            confidence=data.get("confidence", "low"),
            file_changes=file_changes,
            suggested_next_steps=data.get("suggested_next_steps", []),
        )

    except (json.JSONDecodeError, KeyError):
        logger.debug("Could not parse JSON from response, using raw text")
        return Analysis(
            title="Analysis Complete",
            reasoning=text,
            root_cause="See reasoning",
            has_fix=False,
            confidence="low",
            suggested_next_steps=["Review the analysis manually"],
        )


# ---------------------------------------------------------------------------
# Conversation compression
# ---------------------------------------------------------------------------


def _compress_conversation(messages: list[dict]) -> list[dict]:
    """Compress middle messages to save tokens, keeping first and last 4."""
    if len(messages) <= 6:
        return messages

    first = messages[0]
    recent = messages[-4:]
    middle = messages[1:-4]

    # Extract tool call summary from middle
    tool_calls: list[str] = []
    for msg in middle:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(f"- {block.get('name')}: {block.get('input', {})}")

    summary = f"[COMPRESSED — {len(middle)} messages summarized]\n"
    if tool_calls:
        summary += f"Tools used ({len(tool_calls)} calls):\n"
        summary += "\n".join(tool_calls[:5])
        if len(tool_calls) > 5:
            summary += f"\n... and {len(tool_calls) - 5} more"

    logger.info(f"  Compressed conversation: {len(messages)} → 6 messages")

    return [first, {"role": "user", "content": summary}, *recent]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_content(content: list) -> list[dict]:
    """Serialize Claude's response content blocks to dict format."""
    result: list[dict] = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        elif block.type == "thinking":
            # Skip thinking blocks in conversation history
            pass
    return result


def _brief(d: dict) -> str:
    """Brief string repr of tool input for logging."""
    parts = [f"{k}={repr(v)[:40]}" for k, v in d.items()]
    return ", ".join(parts)
