"""System prompt and tool definitions for Claude analysis."""

from __future__ import annotations

SYSTEM_PROMPT = """You are NightWatch, an AI agent that analyzes Ruby on Rails production errors.

Given error data from New Relic, you MUST:
1. Search and read the actual codebase using your tools
2. Identify the root cause from source code
3. Propose a concrete fix if possible

MANDATORY: Always use search_code and read_file to examine the actual code. Never guess.

Investigation steps:
1. Extract controller/action from transactionName
   (e.g. "Controller/products/show" → search for "ProductsController")
2. search_code to find the file
3. read_file to examine it
4. Search for related models, services, concerns
5. Read files referenced in error messages

If one search fails, try variations: action name, error class, keywords from the message.

The codebase is a Ruby on Rails application:
- Controllers: app/controllers/**/*_controller.rb
- Models: app/models/**/*.rb
- Services: app/services/**/*.rb
- Jobs: app/jobs/**/*.rb
- Concerns: app/controllers/concerns/*.rb, app/models/concerns/*.rb

Understanding New Relic trace data:
- transaction_errors[].error.class: Ruby exception class
- transaction_errors[].error.message: Error message with details
- transaction_errors[].transactionName: Rails controller/action (KEY — use to find code)
- transaction_errors[].path: HTTP path
- error_traces[]: Detailed traces with stack traces and fingerprints"""


# Tool definitions with strict mode for structured outputs
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the GitHub repository. Use this to examine source code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root (e.g. 'app/models/user.rb')",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search for code patterns in the repository."
            " Returns file paths and matched lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — method name, class name, error message, etc.",
                },
                "file_extension": {
                    "type": "string",
                    "description": "Optional file extension filter (e.g. 'rb', 'erb')",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_directory",
        "description": "List files and subdirectories in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to repo root (e.g. 'app/models')",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_error_traces",
        "description": "Fetch additional error traces from New Relic for the current error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of trace samples to fetch (default 5)",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


def build_analysis_prompt(
    error_class: str,
    transaction: str,
    message: str,
    occurrences: int,
    trace_summary: str,
    prior_analyses: list | None = None,
    research_context: object | None = None,
) -> str:
    """Build the initial user message for Claude's analysis of an error."""
    prompt = f"""Analyze this production error and propose a fix:

## Error Information
- **Exception Class**: `{error_class}`
- **Transaction**: `{transaction}`
- **Message**: `{message[:500]}`
- **Occurrences**: {occurrences}

## Trace Data
{trace_summary}

**Instructions**: The `transactionName` tells you which controller/action \
is failing. Use search_code to find the relevant code, then read_file to \
examine it. Search for related models and services."""

    # Phase 1: Prior knowledge from knowledge base
    if prior_analyses:
        prompt += "\n\n## Prior Knowledge\n\n"
        prompt += (
            "NightWatch has analyzed similar errors before. "
            "Use this as context but verify independently — "
            "the root cause may differ this time.\n\n"
        )
        for i, prior in enumerate(prior_analyses, 1):
            prompt += f"### Prior Analysis #{i} (match: {prior.match_score:.0%})\n"
            prompt += f"- **Error**: `{prior.error_class}` in `{prior.transaction}`\n"
            prompt += f"- **Root cause**: {prior.root_cause}\n"
            prompt += f"- **Confidence**: {prior.fix_confidence}\n"
            prompt += f"- **Had fix**: {'Yes' if prior.has_fix else 'No'}\n"
            prompt += f"- **Summary**: {prior.summary}\n\n"

    # Phase 2: Pre-fetched research context (accepts ResearchContext dataclass)
    if research_context is not None:
        file_previews = getattr(research_context, "file_previews", {})
        correlated_prs = getattr(research_context, "correlated_prs", [])

        if file_previews:
            prompt += "\n\n## Pre-Fetched Source Files\n\n"
            prompt += (
                "These files were identified as likely relevant based on the "
                "transaction name and stack traces. You can read_file for full "
                "content or search_code for related files.\n\n"
            )
            for path, content in file_previews.items():
                prompt += f"### `{path}` (first 100 lines)\n```ruby\n{content}\n```\n\n"

        if correlated_prs:
            prompt += "\n\n## Recently Merged PRs (Possible Cause)\n\n"
            for pr in correlated_prs[:3]:
                changed = ", ".join(pr.changed_files[:5]) if pr.changed_files else "N/A"
                prompt += (
                    f"- **PR #{pr.number}**: {pr.title} "
                    f"(merged {pr.merged_at}, overlap: {pr.overlap_score:.0%})\n"
                    f"  Changed: {changed}\n"
                )

    return prompt


def summarize_traces(traces: dict, max_errors: int = 3) -> str:
    """Summarize trace data into a compact string for Claude's context."""
    parts: list[str] = []

    # Transaction errors
    tx_errors = traces.get("transaction_errors", [])
    if tx_errors:
        parts.append(f"### Transaction Errors ({len(tx_errors)} total)")
        for i, err in enumerate(tx_errors[:max_errors]):
            parts.append(
                f"**Error {i + 1}**: `{err.get('error.class', 'Unknown')}` — "
                f"`{str(err.get('error.message', ''))[:300]}`\n"
                f"  Transaction: `{err.get('transactionName', 'N/A')}` | "
                f"Path: `{err.get('path', 'N/A')}` | Host: `{err.get('host', 'N/A')}`"
            )

    # Error traces with stack traces
    error_traces = traces.get("error_traces", [])
    if error_traces:
        parts.append(f"\n### Stack Traces ({len(error_traces)} total)")
        for i, trace in enumerate(error_traces[:max_errors]):
            stack = trace.get(
                "error.stack_trace", trace.get("stackTrace", "N/A")
            )
            if isinstance(stack, str) and len(stack) > 500:
                stack = stack[:500] + "..."
            parts.append(
                f"**Trace {i + 1}**: "
                f"`{str(trace.get('error.message', trace.get('message', 'N/A')))[:200]}`\n"
                f"```\n{stack}\n```"
            )

    return "\n".join(parts) if parts else "No trace data available."
