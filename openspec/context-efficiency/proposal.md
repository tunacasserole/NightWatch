# OPENSPEC: Context Efficiency & Conversation Management

**Status**: Approved
**Approved**: 2026-02-05
**Author**: Claude (AI-assisted)
**Date**: 2026-02-05
**Scope**: NightWatch conversation compaction, token efficiency, turn limiting, context management

---

## Executive Summary

NightWatch currently spends **3–10K tokens per error analysis** across 5–15 agentic loop iterations. With default settings (5 errors/run), a single run consumes **15–50K tokens**. This proposal introduces 7 optimization layers that collectively reduce token usage by **40–60%** while improving analysis quality through better context preservation.

The optimizations draw from three sources:
1. **TheFixer patterns** — battle-tested in production (vector memory, two-phase analysis, adaptive iteration limits, code caching)
2. **Anthropic SDK features** — newly available server-side compaction, context editing, thinking block clearing, 1hr prompt caching
3. **NightWatch-native improvements** — token budgeting, cross-error context sharing, parallel analysis

---

## Current State Analysis

### What NightWatch Already Does Well

| Mechanism | Implementation | Savings |
|-----------|---------------|---------|
| Prompt caching (ephemeral) | `cache_control: {"type": "ephemeral"}` on system prompt | ~800 tokens/error after first |
| Conversation compression | Keep first + last 4 messages at 6+ iterations | ~60% message reduction |
| Trace summarization | Top 3 errors + 3 traces, 500-char stack truncation | ~80% trace reduction |
| Structured outputs | Pydantic JSON schema, no regex parsing | Eliminates retries |
| Rate-limit backoff | Exponential backoff with jitter (15s–120s) | Prevents 429 waste |

### What's Missing (Ranked by Impact)

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| Server-side compaction (Anthropic beta) | High — automatic, zero-code summarization | Low | P0 |
| Context editing (clear tool results + thinking) | High — 30-50% reduction in agentic loops | Low | P0 |
| Token budgeting per error | High — prevents runaway conversations | Low | P0 |
| Adaptive iteration limits by error complexity | Medium — 20-40% fewer wasted iterations | Low | P1 |
| Cross-error knowledge sharing | Medium — skip re-analysis of similar patterns | Medium | P1 |
| Message Batching API for non-urgent runs | Medium — 50% cost reduction | Medium | P1 |
| Parallel error analysis | Medium — 3-5x faster runs | Medium | P2 |
| Code cache for GitHub API calls | Low — reduces GitHub rate limit pressure | Low | P2 |
| 1-hour prompt cache TTL | Low — useful for scheduled runs | Low | P3 |

---

## Proposed Optimizations

### Layer 1: Server-Side Compaction (P0)

**What**: Use Anthropic's `compact-2026-01-12` beta to automatically summarize conversation history when approaching context limits, instead of our manual `_compress_conversation()`.

**Why**: Server-side compaction is handled by Claude itself — it understands what's important in the conversation and produces higher-quality summaries than our naive "keep first + last 4" approach.

**How**:

```python
# analyzer.py — replace manual compression with server-side compaction
response = client.beta.messages.create(
    betas=["compact-2026-01-12"],
    model=model,
    max_tokens=16384,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}
    }],
    tools=TOOLS,
    messages=messages,
    thinking={"type": "enabled", "budget_tokens": thinking_budget},
    context_management={
        "edits": [{
            "type": "compact_20260112",
            "trigger": {"type": "input_tokens", "value": 50000},
            "instructions": (
                "Preserve: error class, transaction name, file paths examined, "
                "code patterns found, root cause hypotheses, and tool call results "
                "that revealed important information. "
                "Discard: redundant file listings, failed search attempts, "
                "and intermediate reasoning that led to dead ends."
            ),
            "pause_after_compaction": True,
        }]
    },
)

# Handle compaction pause for token budget enforcement
if response.stop_reason == "compaction":
    messages.append({"role": "assistant", "content": response.content})
    # Check if we've exceeded per-error token budget
    if total_tokens_used > per_error_token_budget:
        # Force wrap-up
        messages.append({
            "role": "user",
            "content": "Token budget reached. Provide your best analysis now with what you've found."
        })
```

**Estimated savings**: Replaces manual compression. Higher quality summaries preserve critical investigation context. Triggers automatically — no iteration counting needed.

**Migration**: Remove `_compress_conversation()` entirely. The server handles it.

---

### Layer 2: Context Editing — Clear Tool Results & Thinking (P0)

**What**: Use Anthropic's context editing betas to automatically clear stale tool results and old thinking blocks from the conversation.

**Why**: In a typical 10-iteration analysis, tool results from iterations 1–5 are rarely relevant by iteration 8. Thinking blocks from early iterations consume tokens but add no value to later reasoning. Context editing removes them server-side.

**How**:

```python
# analyzer.py — add context editing alongside compaction
context_management={
    "edits": [
        # Clear old thinking blocks first (must come first in array)
        {
            "type": "clear_thinking_20251015",
            "keep": {"type": "thinking_turns", "value": 2},  # Keep last 2 turns
        },
        # Clear old tool results
        {
            "type": "clear_tool_uses_20250919",
            "trigger": {"type": "input_tokens", "value": 30000},
            "keep": {"type": "tool_uses", "value": 4},  # Keep last 4 tool calls
            "clear_at_least": {"type": "input_tokens", "value": 5000},
        },
        # Server-side compaction as safety net
        {
            "type": "compact_20260112",
            "trigger": {"type": "input_tokens", "value": 50000},
            "instructions": "Preserve error analysis context...",
        },
    ]
}
```

**Estimated savings**: 30–50% token reduction in agentic loops. Most tool results (file contents, search results) are large and stale after a few iterations.

**Layering**: Context editing fires first (at 30K tokens), compaction fires as backup (at 50K tokens). They compose cleanly.

---

### Layer 3: Token Budgeting Per Error (P0)

**What**: Set a hard token budget per error analysis. If exceeded, force Claude to wrap up with its best analysis so far.

**Why**: Currently, NightWatch has no per-error cost ceiling. A complex error can consume 15+ iterations and 20K+ tokens while a simple NoMethodError might only need 3 iterations and 2K tokens. Token budgeting ensures predictable cost per run.

**How**:

```python
# models.py — add to config
class Settings(BaseSettings):
    # ... existing settings ...
    nightwatch_token_budget_per_error: int = 30000  # Default 30K tokens per error
    nightwatch_total_token_budget: int = 200000     # Default 200K tokens per run

# analyzer.py — enforce budget
total_tokens_this_error = 0

while iteration < max_iterations:
    response = client.beta.messages.create(...)

    # Track cumulative tokens
    iteration_tokens = (
        response.usage.input_tokens +
        response.usage.output_tokens
    )
    total_tokens_this_error += iteration_tokens

    # Budget check
    if total_tokens_this_error > settings.token_budget_per_error:
        logger.warning(
            f"Token budget exceeded: {total_tokens_this_error}/{settings.token_budget_per_error}. "
            f"Forcing wrap-up at iteration {iteration}."
        )
        # Inject wrap-up message
        messages.append({
            "role": "user",
            "content": (
                "IMPORTANT: You've used your token budget for this error. "
                "Provide your analysis NOW based on what you've found so far. "
                "Use the standard JSON format."
            )
        })
        # One final response to get the analysis
        final_response = client.beta.messages.create(...)
        return _parse_analysis(final_response)
```

**Estimated savings**: Prevents runaway conversations. Typical savings of 20–40% on complex errors that would otherwise iterate to max.

---

### Layer 4: Adaptive Iteration Limits (P1)

**What**: Calculate max iterations dynamically based on error complexity, borrowing TheFixer's pattern.

**Why**: NightWatch currently uses a flat `max_iterations=15` for all errors. A `NoMethodError` in a controller typically needs 3–5 iterations. A `SystemStackError` with recursive dependencies might need 10+. Adaptive limits save tokens on simple errors.

**How**:

```python
# analyzer.py — new function
def _calculate_max_iterations(error: ErrorGroup, traces: TraceData | None) -> int:
    """Calculate iteration limit based on error complexity."""
    error_class = error.error_class

    # Simple errors — straightforward to diagnose
    SIMPLE = {"NoMethodError", "NameError", "ArgumentError", "TypeError",
              "KeyError", "IndexError", "AttributeError"}
    if error_class in SIMPLE:
        return 7

    # Auth errors — usually quick to identify
    AUTH = {"NotAuthorizedError", "AuthenticationError", "Forbidden"}
    if any(auth in error_class for auth in AUTH):
        return 5

    # Complex errors — require deeper investigation
    COMPLEX = {"SystemStackError", "Timeout", "ConnectionError",
               "DeadlockDetected", "SegmentationFault", "NoMemoryError"}
    if any(c in error_class for c in COMPLEX):
        return 15

    # Database errors — moderate complexity
    DB = {"ActiveRecord", "PG::", "Mysql2", "StatementInvalid"}
    if any(db in error_class for db in DB):
        return 10

    return 10  # Default for unknown types
```

**Estimated savings**: 20–40% fewer iterations on simple errors. No impact on complex errors that genuinely need deep investigation.

---

### Layer 5: Adaptive Thinking Budget (P1)

**What**: Scale Claude's extended thinking budget based on iteration number and error complexity. Early iterations need more thinking (understanding the problem), later iterations need less (executing the fix).

**Why**: NightWatch currently allocates a flat `budget_tokens=8000` for thinking on every iteration. Iteration 1 (understanding the error) benefits from deep thinking. Iteration 8 (reading a file Claude already knows it needs) does not.

**How**:

```python
# analyzer.py — dynamic thinking budget
def _calculate_thinking_budget(
    iteration: int,
    max_iterations: int,
    error_complexity: str,  # "simple" | "moderate" | "complex"
) -> int:
    """Scale thinking budget by iteration and complexity."""

    BASE_BUDGETS = {
        "simple": 4000,
        "moderate": 8000,
        "complex": 12000,
    }
    base = BASE_BUDGETS.get(error_complexity, 8000)

    # Front-load thinking: iterations 1-2 get full budget,
    # then decay linearly to 25% of base by final iteration
    progress = iteration / max(max_iterations - 1, 1)
    scale = max(0.25, 1.0 - (progress * 0.75))

    return int(base * scale)

# Usage in the loop:
thinking_budget = _calculate_thinking_budget(iteration, max_iterations, complexity)
response = client.beta.messages.create(
    ...,
    thinking={"type": "enabled", "budget_tokens": thinking_budget},
)
```

**Estimated savings**: 15–30% reduction in thinking tokens. Most iterations after the first 2–3 are mechanical (read file, search code) and don't benefit from deep reasoning.

---

### Layer 6: Cross-Error Context Sharing (P1)

**What**: After analyzing each error, store a compact summary. Feed summaries of previously analyzed errors into subsequent analyses so Claude can recognize patterns and avoid redundant investigation.

**Why**: Production errors often cluster. If 3/5 errors are in the same Rails controller or share the same dependency, Claude currently investigates each from scratch. Cross-error context lets it say "I already looked at this service in Error #1 — the issue is the same pattern."

**How**:

```python
# runner.py — accumulate cross-error context
cross_error_context: list[str] = []

for i, error in enumerate(errors_to_analyze):
    # Build context from previous analyses
    prior_context = ""
    if cross_error_context:
        prior_context = (
            "\n\n## Previously Analyzed Errors This Run\n"
            + "\n".join(f"- {ctx}" for ctx in cross_error_context)
            + "\n\nIf this error is related to a previous one, reference it. "
            "Don't re-investigate files you've already analyzed."
        )

    result = analyze_error(error, traces, prior_context=prior_context)

    # Store compact summary for next error
    if result.analysis:
        summary = (
            f"Error #{i+1}: {error.error_class} in {error.transaction} — "
            f"Root cause: {result.analysis.root_cause[:200]}. "
            f"Files examined: {', '.join(fc.path for fc in result.analysis.file_changes[:3])}"
        )
        cross_error_context.append(summary)
```

**Estimated savings**: 10–30% on errors 2–5 in a run, depending on clustering. Zero cost on error #1.

---

### Layer 7: Message Batching for Scheduled Runs (P1)

**What**: Use Anthropic's Message Batching API for non-urgent scheduled (cron) runs. Batching gives a 50% cost discount but has up to 24-hour processing time.

**Why**: NightWatch runs as a daily cron job. The 24-hour processing window is acceptable for overnight batch runs. This is pure cost savings with zero code complexity in the agentic loop itself.

**How**:

```python
# runner.py — batch mode for cron runs
class BatchAnalyzer:
    """Batch mode: submit all error analyses as a single batch request.

    50% cost reduction. Up to 24h processing time.
    Only for scheduled (cron) runs, not interactive use.
    """

    def submit_batch(self, errors: list[ErrorGroup], traces: dict) -> str:
        """Submit batch of error analyses. Returns batch_id."""
        requests = []
        for i, error in enumerate(errors):
            initial_message = build_initial_message(error, traces.get(error.key))
            requests.append({
                "custom_id": f"error-{i}-{error.error_class}",
                "params": {
                    "model": settings.model,
                    "max_tokens": 16384,
                    "system": [{"type": "text", "text": SYSTEM_PROMPT}],
                    "tools": TOOLS,
                    "messages": [{"role": "user", "content": initial_message}],
                    "thinking": {"type": "enabled", "budget_tokens": 8000},
                }
            })

        batch = self.client.messages.batches.create(requests=requests)
        return batch.id

    def poll_results(self, batch_id: str) -> list[ErrorAnalysisResult]:
        """Poll for batch completion. Called by a follow-up cron job."""
        batch = self.client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None  # Not ready yet

        results = []
        for result in self.client.messages.batches.results(batch_id):
            analysis = _parse_analysis(result.result.message)
            results.append(analysis)
        return results
```

**Estimated savings**: 50% cost reduction on all batch runs. Requires a two-phase cron setup (submit + collect).

**Limitation**: Batching only works for the **first** API call per error (no agentic loop). For errors that need tool use, fall back to standard mode. Best suited for a "triage pass" — batch-classify errors, then run the full agentic loop only on errors that need deep investigation.

---

### Layer 8: Code Cache for GitHub API (P2)

**What**: Cache GitHub file reads and code searches during a run. If Claude reads the same file across multiple error analyses, return the cached version.

**Why**: TheFixer's CodeCache proved valuable — hit rates of 30–50% in production. Claude often reads the same files across related errors (e.g., `ApplicationController`, shared service classes).

**How**:

```python
# github.py — add in-memory cache
from functools import lru_cache
from datetime import datetime, timedelta

class CodeCache:
    """Cache GitHub API results during a NightWatch run."""

    def __init__(self, ttl_minutes: int = 30):
        self._cache: dict[str, tuple[str, datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> str | None:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
                self._hits += 1
                return value
            del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: str) -> None:
        self._cache[key] = (value, datetime.now())

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return (self._hits / total * 100) if total > 0 else 0.0

# Usage in tool execution:
code_cache = CodeCache(ttl_minutes=30)

def execute_read_file(path: str) -> str:
    cached = code_cache.get(f"file:{path}")
    if cached:
        return cached
    content = github_client.get_file_content(path)
    code_cache.set(f"file:{path}", content)
    return content
```

**Estimated savings**: Reduces GitHub API calls by 30–50% across multi-error runs. Prevents GitHub rate limiting on large runs.

---

## Compatibility Matrix

| Optimization | Anthropic SDK Version | Beta Required | Model Requirement |
|-------------|----------------------|---------------|-------------------|
| Server-side compaction | >=0.77.0 | `compact-2026-01-12` | Claude Opus 4.6 only |
| Context editing (tools) | >=0.77.0 | `context-management-2025-06-27` | All Claude models |
| Context editing (thinking) | >=0.77.0 | `context-management-2025-06-27` | Models with thinking |
| Token counting | >=0.77.0 | None | All |
| Message batching | >=0.77.0 | None | All |
| 1-hour cache TTL | >=0.77.0 | None | All |
| Prompt caching | >=0.77.0 | None (GA) | All |

**Important**: Server-side compaction currently requires **Claude Opus 4.6** (`claude-opus-4-6`). NightWatch defaults to `claude-sonnet-4-5-20250929`. Options:
- Use compaction only when `NIGHTWATCH_MODEL` is set to Opus
- Fall back to manual compression for Sonnet (current behavior)
- Make compaction opt-in via `NIGHTWATCH_USE_COMPACTION=true`

---

## Cost Impact Projection

### Current Cost (5 errors/run, Sonnet)

| Component | Tokens | Cost (Sonnet) |
|-----------|--------|---------------|
| System prompt (cached after #1) | ~2K × 5 = 10K, cached 8K | ~$0.003 |
| Tool definitions (cached) | ~1K × 5 = 5K, cached 4K | ~$0.001 |
| Conversation messages | ~3K × 5 = 15K avg | ~$0.045 |
| Tool results | ~5K × 5 = 25K avg | ~$0.075 |
| Extended thinking | ~8K × 5 = 40K avg | ~$0.120 |
| Output tokens | ~2K × 5 = 10K avg | ~$0.100 |
| **Total per run** | **~105K** | **~$0.34** |

### Projected Cost (with all optimizations)

| Optimization | Token Reduction | Cost Savings |
|-------------|----------------|--------------|
| Context editing (clear tools + thinking) | -25K | -$0.075 |
| Token budgeting (prevent runaway) | -10K | -$0.030 |
| Adaptive iterations | -8K | -$0.024 |
| Adaptive thinking budget | -10K | -$0.030 |
| Cross-error context | -5K | -$0.015 |
| **Projected total** | **~47K** | **~$0.17** |
| **Savings** | **55%** | **50%** |

With Message Batching (cron mode): additional 50% off → **~$0.085/run**

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Compaction loses critical context | Medium | Custom instructions preserve error-specific info; fall back to manual compression |
| Token budget forces premature wrap-up | Medium | Budget is per-error, not per-iteration; wrap-up gets one final response |
| Context editing clears needed tool results | Low | `keep: 4` retains recent results; only old results cleared |
| Batch API doesn't support agentic loops | Low | Use batch for triage only; full loop for selected errors |
| Opus-only compaction limits model choice | Medium | Feature-gate compaction behind model check; manual compression fallback |
| Cross-error context introduces noise | Low | Summaries are <200 chars each; max 4 prior summaries |

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Tokens per error (avg) | ~21K | ~10K | `RunReport.total_tokens / errors_analyzed` |
| Tokens per run (avg) | ~105K | ~50K | `RunReport.total_tokens_used` |
| Cost per run | ~$0.34 | ~$0.17 | Token cost calculation |
| Iterations per error (avg) | ~8 | ~5 | `ErrorAnalysisResult.iterations` |
| Analysis quality (fix confidence) | baseline | >=baseline | `RunReport.high_confidence` count |
| Run duration | ~5 min | ~3 min | `RunReport.run_duration_seconds` |

---

## References

- [Anthropic Compaction Beta](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Anthropic Context Editing Beta](https://platform.claude.com/docs/en/build-with-claude/context-editing)
- [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic Message Batching](https://docs.anthropic.com/en/api/creating-message-batches)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- TheFixer source: `/Users/ahenderson/dev/TheFixer/app/services/claude_service.py`
- TheFixer vector memory: `/Users/ahenderson/dev/TheFixer/app/services/vector_memory.py`
