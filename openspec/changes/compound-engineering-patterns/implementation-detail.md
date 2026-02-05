# Implementation Detail: Compound Engineering Patterns

**Proposal**: COMPOUND-001
**Date**: 2026-02-05

---

## Phase 1: Knowledge Foundation — Technical Design

### Solution Document Format

Each analysis result is persisted as a Markdown file with YAML frontmatter:

```markdown
---
error_class: "ActiveRecord::RecordNotFound"
transaction: "Controller/orders/update"
module: "app/controllers/orders_controller.rb"
message: "Couldn't find Order with 'id'=12345"
occurrences: 87
root_cause: "Race condition between order deletion and status update"
fix_confidence: "high"
has_fix: true
pr_number: 1203
issue_number: 427
tags: [activerecord, race-condition, orders, not-found]
first_detected: "2026-02-05"
run_id: "20260205-060000"
iterations_used: 6
tokens_used: 12340
---

# ActiveRecord::RecordNotFound in Orders#update

## Root Cause Analysis

The `OrdersController#update` action calls `Order.find(params[:id])` without
checking if the order still exists. When a concurrent request deletes the order
between the find and update, a RecordNotFound is raised.

## Proposed Fix

Replace `find` with `find_by` and handle the nil case:

```ruby
order = Order.find_by(id: params[:id])
if order.nil?
  render json: { error: "Order not found" }, status: :not_found
  return
end
```

## File Changes

- `app/controllers/orders_controller.rb:45` — Replace `find` with `find_by`
- `app/controllers/orders_controller.rb:47-52` — Add nil guard

## Related Patterns

- Similar race condition in `ProductsController#destroy` (2026-01-28)
- General pattern: always use `find_by` for user-supplied IDs
```

### Knowledge Index Format (`index.yml`)

```yaml
# Auto-generated — do not edit manually
last_updated: "2026-02-05T06:15:00Z"
total_solutions: 47
total_patterns: 8

solutions:
  - id: "20260205-001"
    file: "errors/2026-02-05_activerecord-not-found_orders-update.md"
    error_class: "ActiveRecord::RecordNotFound"
    transaction: "Controller/orders/update"
    fix_confidence: "high"
    tags: [activerecord, race-condition, orders]

  - id: "20260205-002"
    file: "errors/2026-02-05_net-read-timeout_products-show.md"
    error_class: "Net::ReadTimeout"
    transaction: "Controller/products/show"
    fix_confidence: "medium"
    tags: [timeout, external-api, products]

patterns:
  - id: "pattern-001"
    file: "patterns/external-api-timeouts.md"
    title: "External API Timeout Pattern"
    occurrences: 12
    modules: [products, inventory, pricing]
    tags: [timeout, external-api, circuit-breaker]
```

### Python Implementation: `knowledge.py`

```python
"""Knowledge compounding system — NightWatch learns from every run."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from nightwatch.models import ErrorAnalysisResult, ErrorGroup

logger = logging.getLogger("nightwatch.knowledge")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
ERRORS_DIR = KNOWLEDGE_DIR / "errors"
PATTERNS_DIR = KNOWLEDGE_DIR / "patterns"
INDEX_PATH = KNOWLEDGE_DIR / "index.yml"


# ---------------------------------------------------------------------------
# Search (grep-first strategy from compound-engineering)
# ---------------------------------------------------------------------------

def search_prior_knowledge(error: ErrorGroup) -> list[dict]:
    """Search knowledge base for prior analyses of similar errors.

    Uses the grep-first strategy from compound-engineering:
    1. Search index.yml for matching tags/error_class
    2. Read only matching solution documents
    3. Return structured prior knowledge
    """
    if not INDEX_PATH.exists():
        return []

    index = yaml.safe_load(INDEX_PATH.read_text())
    matches = []

    for solution in index.get("solutions", []):
        score = _match_score(error, solution)
        if score > 0:
            matches.append((score, solution))

    # Sort by match score, return top 3
    matches.sort(key=lambda x: x[0], reverse=True)
    results = []

    for score, solution in matches[:3]:
        doc_path = KNOWLEDGE_DIR / solution["file"]
        if doc_path.exists():
            content = doc_path.read_text()
            frontmatter, body = _parse_frontmatter(content)
            results.append({
                "error_class": frontmatter.get("error_class"),
                "transaction": frontmatter.get("transaction"),
                "root_cause": frontmatter.get("root_cause"),
                "fix_confidence": frontmatter.get("fix_confidence"),
                "has_fix": frontmatter.get("has_fix", False),
                "summary": body[:500],  # First 500 chars of analysis
                "match_score": score,
            })

    if results:
        logger.info(f"  Found {len(results)} prior analyses for {error.error_class}")

    return results


def _match_score(error: ErrorGroup, solution: dict) -> float:
    """Score how well a solution matches the current error."""
    score = 0.0

    if solution.get("error_class") == error.error_class:
        score += 0.5  # Same error class is strong signal

    if solution.get("transaction") == error.transaction:
        score += 0.3  # Same transaction is very strong

    # Tag overlap
    solution_tags = set(solution.get("tags", []))
    error_tags = _extract_tags(error)
    overlap = solution_tags & error_tags
    if overlap:
        score += 0.1 * len(overlap)

    return score


def _extract_tags(error: ErrorGroup) -> set[str]:
    """Extract searchable tags from an error group."""
    tags = set()
    # Extract from error class (e.g., "ActiveRecord::RecordNotFound" -> {activerecord, recordnotfound})
    for part in error.error_class.split("::"):
        tags.add(part.lower())
    # Extract from transaction (e.g., "Controller/orders/update" -> {orders, update})
    for part in re.split(r"[/:#]", error.transaction):
        if part and part.lower() not in {"controller", "action"}:
            tags.add(part.lower())
    return tags


# ---------------------------------------------------------------------------
# Write (compound phase)
# ---------------------------------------------------------------------------

def compound_analysis(result: ErrorAnalysisResult) -> Path | None:
    """Persist an analysis result as a knowledge document."""
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)

    slug = _slugify(f"{result.error.error_class}-{result.error.transaction}")
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"{date}_{slug}.md"
    filepath = ERRORS_DIR / filename

    frontmatter = {
        "error_class": result.error.error_class,
        "transaction": result.error.transaction,
        "message": result.error.message[:200],
        "occurrences": result.error.occurrences,
        "root_cause": result.analysis.root_cause,
        "fix_confidence": result.analysis.confidence,
        "has_fix": result.analysis.has_fix,
        "tags": list(_extract_tags(result.error)),
        "first_detected": date,
        "iterations_used": result.iterations,
        "tokens_used": result.tokens_used,
    }

    body = f"# {result.analysis.title}\n\n"
    body += f"## Root Cause\n\n{result.analysis.root_cause}\n\n"
    body += f"## Analysis\n\n{result.analysis.reasoning}\n\n"

    if result.analysis.suggested_next_steps:
        body += "## Next Steps\n\n"
        for step in result.analysis.suggested_next_steps:
            body += f"- {step}\n"

    if result.analysis.file_changes:
        body += "\n## File Changes\n\n"
        for fc in result.analysis.file_changes:
            body += f"- `{fc.path}` — {fc.description}\n"

    content = _render_frontmatter(frontmatter) + "\n" + body
    filepath.write_text(content)

    logger.info(f"  Knowledge: saved {filename}")
    return filepath


def rebuild_index() -> None:
    """Rebuild the knowledge index from all solution documents."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    solutions = []
    patterns = []

    # Index error solutions
    if ERRORS_DIR.exists():
        for path in sorted(ERRORS_DIR.glob("*.md")):
            content = path.read_text()
            fm, _ = _parse_frontmatter(content)
            if fm:
                solutions.append({
                    "file": f"errors/{path.name}",
                    "error_class": fm.get("error_class", ""),
                    "transaction": fm.get("transaction", ""),
                    "fix_confidence": fm.get("fix_confidence", ""),
                    "has_fix": fm.get("has_fix", False),
                    "tags": fm.get("tags", []),
                })

    # Index pattern documents
    if PATTERNS_DIR.exists():
        for path in sorted(PATTERNS_DIR.glob("*.md")):
            content = path.read_text()
            fm, _ = _parse_frontmatter(content)
            if fm:
                patterns.append({
                    "file": f"patterns/{path.name}",
                    "title": fm.get("title", path.stem),
                    "occurrences": fm.get("occurrences", 0),
                    "tags": fm.get("tags", []),
                })

    index = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total_solutions": len(solutions),
        "total_patterns": len(patterns),
        "solutions": solutions,
        "patterns": patterns,
    }

    INDEX_PATH.write_text(yaml.dump(index, default_flow_style=False, sort_keys=False))
    logger.info(f"  Knowledge index rebuilt: {len(solutions)} solutions, {len(patterns)} patterns")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from Markdown content."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1])
        return fm or {}, parts[2]
    except yaml.YAMLError:
        return {}, content


def _render_frontmatter(data: dict) -> str:
    """Render dict as YAML frontmatter block."""
    yml = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return f"---\n{yml}---\n"


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")[:60]
```

### Runner Integration

Add to `runner.py` after Step 11:

```python
from nightwatch.knowledge import compound_analysis, rebuild_index, search_prior_knowledge

# In the run() function, before analysis:
prior_knowledge = {}
for error in top_errors:
    prior = search_prior_knowledge(error)
    if prior:
        prior_knowledge[id(error)] = prior

# Pass to analyzer:
result = analyze_error(
    error=error,
    traces=traces_map[id(error)],
    github_client=gh,
    newrelic_client=nr,
    prior_analyses=prior_knowledge.get(id(error), []),  # NEW
)

# After Step 11, add Step 12:
# Step 12: Compound — persist learnings
if not dry_run:
    for result in analyses:
        compound_analysis(result)
    rebuild_index()
    logger.info(f"Knowledge base updated: {len(analyses)} new entries")
```

### Prompt Integration

Modify `prompts.py` to include prior knowledge:

```python
def build_analysis_prompt(
    error_class: str,
    transaction: str,
    message: str,
    occurrences: int,
    trace_summary: str,
    prior_analyses: list[dict] | None = None,  # NEW
) -> str:
    prompt = f"""Analyze this production error:
...existing prompt...
"""

    if prior_analyses:
        prompt += "\n\n## Prior Knowledge\n\n"
        prompt += "NightWatch has analyzed similar errors before:\n\n"
        for i, prior in enumerate(prior_analyses, 1):
            prompt += f"### Prior Analysis #{i}\n"
            prompt += f"- Error: {prior['error_class']} in {prior['transaction']}\n"
            prompt += f"- Root cause: {prior['root_cause']}\n"
            prompt += f"- Fix confidence: {prior['fix_confidence']}\n"
            prompt += f"- Summary: {prior['summary']}\n\n"
        prompt += (
            "Use this prior knowledge as context, but verify independently. "
            "The error may have a different root cause this time.\n"
        )

    return prompt
```

---

## Phase 2: Research Enhancement — Technical Design

### Pre-Analysis Research Module (`research.py`)

```python
"""Pre-analysis research — gather context before Claude's main loop."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from nightwatch.knowledge import search_prior_knowledge
from nightwatch.models import ErrorGroup, TraceData

logger = logging.getLogger("nightwatch.research")


@dataclass
class ResearchContext:
    """Pre-gathered context to inject into analysis prompt."""
    prior_analyses: list[dict] = field(default_factory=list)
    likely_files: list[str] = field(default_factory=list)
    correlated_prs: list[dict] = field(default_factory=list)
    similar_ignored: list[dict] = field(default_factory=list)


def research_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: any,
) -> ResearchContext:
    """Gather all available context before the main analysis loop."""
    ctx = ResearchContext()

    # 1. Knowledge base search
    ctx.prior_analyses = search_prior_knowledge(error)

    # 2. Pre-fetch likely relevant files
    ctx.likely_files = _infer_relevant_files(error, traces, github_client)

    # 3. Correlated PRs (handled separately in runner.py, passed in)

    return ctx


def _infer_relevant_files(
    error: ErrorGroup,
    traces: TraceData,
    github_client: any,
) -> list[str]:
    """Infer likely relevant source files from error metadata.

    Extracts file paths from:
    - Transaction name (Controller/orders/update -> app/controllers/orders_controller.rb)
    - Stack traces (if available)
    - Error message (if it mentions a file)
    """
    files = []

    # From transaction name
    tx = error.transaction
    if "Controller/" in tx:
        # "Controller/orders/update" -> "app/controllers/orders_controller.rb"
        parts = tx.replace("Controller/", "").split("/")
        if parts:
            controller = parts[0]
            path = f"app/controllers/{controller}_controller.rb"
            files.append(path)

            # Also check for related model
            model_path = f"app/models/{controller.rstrip('s')}.rb"
            files.append(model_path)

    # From stack traces
    for trace in traces.error_traces[:3]:  # Check first 3 traces
        if isinstance(trace, dict):
            for frame in trace.get("stackTrace", [])[:5]:
                filepath = frame.get("filepath", "")
                if filepath and not filepath.startswith("/"):
                    files.append(filepath)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    return unique[:10]  # Cap at 10 files
```

---

## Phase 3: Agent Configuration — Technical Design

### Agent Definition Schema

```python
"""Agent configuration loaded from Markdown files with YAML frontmatter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentConfig:
    """Configuration for a NightWatch analysis agent."""
    name: str
    system_prompt: str
    model: str = "claude-sonnet-4-5-20250929"
    thinking_budget: int = 8000
    max_iterations: int = 15
    tools: list[str] = field(default_factory=lambda: [
        "read_file", "search_code", "list_directory", "get_error_traces"
    ])
    description: str = ""


AGENTS_DIR = Path(__file__).parent / "agents"


def load_agent(name: str = "base-analyzer") -> AgentConfig:
    """Load an agent definition from agents/ directory.

    Falls back to inline default if file not found.
    """
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        return _default_agent()

    content = path.read_text()
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return AgentConfig(name=name, system_prompt=content)

    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    return AgentConfig(
        name=fm.get("name", name),
        system_prompt=body,
        model=fm.get("model", "claude-sonnet-4-5-20250929"),
        thinking_budget=fm.get("thinking_budget", 8000),
        max_iterations=fm.get("max_iterations", 15),
        tools=fm.get("tools", ["read_file", "search_code", "list_directory", "get_error_traces"]),
        description=fm.get("description", ""),
    )


def _default_agent() -> AgentConfig:
    """Return the default base analyzer agent (backward compatibility)."""
    from nightwatch.prompts import SYSTEM_PROMPT
    return AgentConfig(name="base-analyzer", system_prompt=SYSTEM_PROMPT)
```

### Example Agent File: `agents/base-analyzer.md`

```markdown
---
name: "base-analyzer"
description: "Core NightWatch error analysis agent for Ruby on Rails applications"
model: "claude-sonnet-4-5-20250929"
thinking_budget: 8000
max_iterations: 15
tools:
  - read_file
  - search_code
  - list_directory
  - get_error_traces
---

You are NightWatch, an AI agent that analyzes Ruby on Rails production errors
and proposes fixes.

For each error you receive:

1. Extract the controller/action from the transactionName
2. Use search_code to find the relevant controller file
3. Use read_file to examine the actual source code
4. Search for related models, services, and concerns
5. Identify the root cause
6. Propose a concrete fix if possible

## Rules

- ALWAYS search and read the actual source code. Never guess.
- If you find the root cause but aren't sure about the fix, say so.
- If the error is in a gem or third-party code, note that.
- Be specific about file paths and line numbers.
- Consider race conditions, nil references, and edge cases.
- Check for N+1 queries if the error is performance-related.

## Output Format

Return your analysis as JSON with these fields:
- title: Short descriptive title
- reasoning: Detailed analysis chain
- root_cause: Specific root cause identified
- has_fix: Whether you can propose a concrete fix
- confidence: "high", "medium", or "low"
- file_changes: Array of {path, action, content, description}
- suggested_next_steps: Array of actionable next steps
```

---

## Extracted Algorithm: Grep-First Search

The compound-engineering `learnings-researcher` uses an efficient search strategy that avoids reading every document in the knowledge base:

```
1. Open index.yml (small, structured)
2. Score each entry against the search criteria (tag overlap, field match)
3. Only read the top N matching full documents
4. Extract and synthesize relevant information
```

This is O(index_size) for the search + O(N) for reading matches, instead of O(total_documents) for reading everything. For a knowledge base with hundreds of entries, this is significantly faster.

NightWatch's implementation in `knowledge.py:search_prior_knowledge()` follows this exact pattern.

---

## Extracted Pattern: Agent Description with Examples

From compound-engineering, agents use `<example>` blocks in their descriptions to improve invocation accuracy:

```markdown
<example>
  <context>Error: ActiveRecord::RecordNotFound in OrdersController#update</context>
  <analysis>
    1. Read orders_controller.rb — found Order.find(params[:id]) on line 45
    2. Searched for concurrent deletion patterns — found background job
    3. Root cause: race condition between job and controller
    4. Fix: use find_by with nil guard
  </analysis>
</example>
```

This pattern helps Claude understand *how* to approach analysis, not just *what* to analyze. Consider including 2-3 examples in each agent definition file.
