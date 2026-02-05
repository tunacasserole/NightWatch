"""Claude agentic analysis loop — sync, single-pass, with prompt caching."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import anthropic

from nightwatch.config import get_settings
from nightwatch.models import Analysis, ErrorAnalysisResult, ErrorGroup, FileChange, TraceData
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
) -> ErrorAnalysisResult:
    """Run Claude's agentic loop to analyze a single error.

    Args:
        error: The error group to analyze.
        traces: Pre-fetched trace data for this error.
        github_client: GitHubClient instance (provides read_file, search_code, list_directory).
        newrelic_client: NewRelicClient instance (provides fetch_traces).

    Returns:
        ErrorAnalysisResult with the analysis, iteration count, and token usage.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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
    )

    messages: list[dict] = [{"role": "user", "content": initial_message}]

    iteration = 0
    max_iterations = settings.nightwatch_max_iterations
    total_tokens = 0
    api_calls = 0

    while iteration < max_iterations:
        iteration += 1
        if iteration > 1:
            time.sleep(1.5)  # Rate-limit protection

        logger.info(f"  Iteration {iteration}/{max_iterations}")

        response, tokens = _call_claude_with_retry(
            client=client,
            model=settings.nightwatch_model,
            messages=messages,
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
# Claude API call with retry + prompt caching
# ---------------------------------------------------------------------------


def _call_claude_with_retry(
    client: anthropic.Anthropic,
    model: str,
    messages: list[dict],
    max_retries: int = 5,
    base_delay: float = 15.0,
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
                    "budget_tokens": 8000,
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
    if tool_name == "read_file":
        content = github_client.read_file(tool_input["path"])
        return content if content is not None else f"File not found: {tool_input['path']}"

    if tool_name == "search_code":
        results = github_client.search_code(
            tool_input["query"], tool_input.get("file_extension")
        )
        return json.dumps(results, indent=2) if results else "No matches found"

    if tool_name == "list_directory":
        contents = github_client.list_directory(tool_input["path"])
        if contents:
            return json.dumps(contents, indent=2)
        return f"Directory not found: {tool_input['path']}"

    if tool_name == "get_error_traces":
        # Return pre-fetched traces (avoids extra NR calls during analysis)
        trace_data = {
            "transaction_errors": traces.transaction_errors,
            "error_traces": traces.error_traces,
        }
        return json.dumps(trace_data, indent=2)

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
