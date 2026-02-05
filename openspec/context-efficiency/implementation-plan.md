# Implementation Plan: Context Efficiency & Conversation Management

**Parent**: [proposal.md](./proposal.md)
**Status**: Approved
**Date**: 2026-02-05
**Estimated Total Effort**: 2-3 days (with AI assistance)

---

## Phase 1: Foundation — Zero-Risk Token Savings (Day 1, Morning)

These changes are isolated to `analyzer.py` and require no new dependencies or architectural changes. Each can be implemented and tested independently.

### Task 1.1: Token Budgeting Per Error

**Files**: `nightwatch/analyzer.py`, `nightwatch/config.py`, `nightwatch/models.py`
**Effort**: ~1 hour

**Steps**:
1. Add `nightwatch_token_budget_per_error: int = 30000` to `Settings` in `config.py`
2. Add `nightwatch_total_token_budget: int = 200000` to `Settings`
3. In `analyze_error()` in `analyzer.py`:
   - Track cumulative `total_tokens_this_error` across iterations
   - After each API response, check `total_tokens_this_error > budget`
   - If exceeded: inject wrap-up message, make one final API call, return best analysis
4. Add `tokens_used` tracking to `ErrorAnalysisResult` (already exists — verify accuracy)
5. Log budget warnings: `"Token budget {used}/{budget} — forcing wrap-up"`

**Test**: Mock a conversation that would exceed 30K tokens. Verify it wraps up gracefully and returns a valid `Analysis`.

**Rollback**: Remove budget check. Zero impact on existing behavior.

---

### Task 1.2: Adaptive Iteration Limits

**Files**: `nightwatch/analyzer.py`
**Effort**: ~30 minutes

**Steps**:
1. Add `_calculate_max_iterations(error: ErrorGroup) -> int` function
2. Classify error types:
   - Simple (NoMethodError, NameError, ArgumentError, TypeError, KeyError): **7 iterations**
   - Auth (NotAuthorizedError, Forbidden, AuthenticationError): **5 iterations**
   - Database (ActiveRecord, PG::, StatementInvalid): **10 iterations**
   - Complex (SystemStackError, Timeout, ConnectionError, NoMemoryError): **15 iterations**
   - Default: **10 iterations**
3. Replace `max_iterations = settings.nightwatch_max_iterations` with calculated value
4. Keep `settings.nightwatch_max_iterations` as absolute ceiling (never exceed it)
5. Log: `"Error class {cls} → max_iterations={n} (ceiling: {settings_max})"`

**Test**: Pass different `ErrorGroup` objects with various `error_class` values. Verify correct limits.

**Rollback**: Revert to flat `settings.nightwatch_max_iterations`.

---

### Task 1.3: Adaptive Thinking Budget

**Files**: `nightwatch/analyzer.py`
**Effort**: ~30 minutes

**Steps**:
1. Add `_calculate_thinking_budget(iteration, max_iterations, error_class) -> int`
2. Classify error complexity: `simple` (4K base), `moderate` (8K base), `complex` (12K base)
3. Apply decay: full budget for iterations 1–2, linear decay to 25% by final iteration
4. Floor at 2000 tokens (minimum for any useful thinking)
5. Replace flat `budget_tokens=8000` with dynamic value
6. Log: `"Iteration {i}/{max}: thinking_budget={budget} (base={base}, scale={scale:.0%})"`

**Test**: Verify budget calculations for iteration 1 vs iteration 10 for each complexity tier.

**Rollback**: Revert to flat `budget_tokens=8000`.

---

## Phase 2: Anthropic Beta Features — Server-Side Optimization (Day 1, Afternoon)

These changes leverage new Anthropic SDK beta features. They require `anthropic>=0.77.0` (already in `pyproject.toml`) and beta headers.

### Task 2.1: Context Editing — Clear Tool Results & Thinking Blocks

**Files**: `nightwatch/analyzer.py`
**Effort**: ~1 hour

**Steps**:
1. Switch from `client.messages.create()` to `client.beta.messages.create()`
2. Add `betas=["context-management-2025-06-27"]` parameter
3. Add `context_management` parameter with two edits:
   ```python
   context_management={
       "edits": [
           {
               "type": "clear_thinking_20251015",
               "keep": {"type": "thinking_turns", "value": 2},
           },
           {
               "type": "clear_tool_uses_20250919",
               "trigger": {"type": "input_tokens", "value": 30000},
               "keep": {"type": "tool_uses", "value": 4},
               "clear_at_least": {"type": "input_tokens", "value": 5000},
           },
       ]
   }
   ```
4. Add token counting before/after to measure savings:
   ```python
   # Pre-count tokens to see context editing effect
   count = client.beta.messages.count_tokens(...)
   logger.info(f"Pre-edit tokens: {count.context_management['original_input_tokens']}, "
               f"Post-edit: {count.input_tokens}")
   ```
5. Update `_serialize_content()` to handle new response content types if needed

**Test**: Run an error analysis that exceeds 30K input tokens. Verify tool results are cleared and thinking blocks are trimmed. Check that analysis quality is maintained.

**Rollback**: Remove `context_management` parameter. Revert to `client.messages.create()`.

**Note**: This works with all Claude models (Sonnet included).

---

### Task 2.2: Server-Side Compaction (Opus Only)

**Files**: `nightwatch/analyzer.py`, `nightwatch/config.py`
**Effort**: ~1.5 hours

**Steps**:
1. Add `nightwatch_use_compaction: bool = False` to `Settings`
2. Add model detection: `is_opus = "opus" in settings.nightwatch_model`
3. If compaction enabled AND model is Opus:
   - Add `"compact-2026-01-12"` to betas list
   - Add compaction edit to `context_management`:
     ```python
     {
         "type": "compact_20260112",
         "trigger": {"type": "input_tokens", "value": 50000},
         "instructions": (
             "Preserve: error class, transaction name, file paths examined, "
             "code patterns found, root cause hypotheses, tool results with "
             "important findings. Discard: redundant file listings, failed "
             "searches, intermediate dead-end reasoning."
         ),
         "pause_after_compaction": True,
     }
     ```
   - Handle `stop_reason == "compaction"`:
     - Append compaction response to messages
     - Check total token budget
     - If over budget: inject wrap-up, get final analysis
     - Otherwise: continue loop
4. If compaction NOT enabled: keep existing `_compress_conversation()` as fallback
5. Log compaction events: `"Server-side compaction triggered at iteration {i}"`

**Test**: Requires Opus model. Set `NIGHTWATCH_MODEL=claude-opus-4-6` and `NIGHTWATCH_USE_COMPACTION=true`. Run a complex error that triggers compaction. Verify conversation continues correctly after compaction.

**Rollback**: Set `NIGHTWATCH_USE_COMPACTION=false`. Falls back to manual compression.

---

### Task 2.3: Remove Manual Compression (Conditional)

**Files**: `nightwatch/analyzer.py`
**Effort**: ~15 minutes

**Steps**:
1. When compaction is enabled, skip the manual `_compress_conversation()` call entirely
2. Keep `_compress_conversation()` as fallback for non-Opus models
3. Add conditional:
   ```python
   if not use_compaction and iteration >= 6 and len(messages) > 8:
       messages = _compress_conversation(messages)
   # If compaction is enabled, server handles it automatically
   ```

**Test**: Verify manual compression still works when compaction is disabled.

---

## Phase 3: Cross-Error Intelligence (Day 2, Morning)

### Task 3.1: Cross-Error Context Sharing

**Files**: `nightwatch/runner.py`, `nightwatch/analyzer.py`, `nightwatch/prompts.py`
**Effort**: ~1.5 hours

**Steps**:
1. In `runner.py`, add `cross_error_context: list[str] = []` before the error analysis loop
2. After each successful analysis, build a compact summary:
   ```python
   summary = (
       f"Error #{i+1}: {error.error_class} in {error.transaction} — "
       f"Root cause: {result.analysis.root_cause[:200]}. "
       f"Files: {', '.join(fc.path for fc in result.analysis.file_changes[:3])}"
   )
   cross_error_context.append(summary)
   ```
3. Pass `prior_context: str | None` to `analyze_error()`
4. In `analyze_error()`, prepend prior context to the initial user message:
   ```python
   if prior_context:
       initial_message = prior_context + "\n\n---\n\n" + initial_message
   ```
5. Update `prompts.py` system prompt to include instruction:
   ```
   If you see "Previously Analyzed Errors", look for patterns.
   If this error is related to a previous one, say so and avoid
   re-investigating files you've already seen.
   ```
6. Cap at 4 prior summaries (most recent) to avoid bloating context

**Test**: Analyze 3 related errors (same controller). Verify error #3 references findings from #1 and #2. Compare token usage vs. without cross-error context.

**Rollback**: Remove `prior_context` parameter. Each error goes back to isolated analysis.

---

### Task 3.2: Code Cache for GitHub API

**Files**: `nightwatch/github.py` (new class), `nightwatch/analyzer.py` (integrate)
**Effort**: ~1 hour

**Steps**:
1. Add `CodeCache` class to `github.py`:
   ```python
   class CodeCache:
       def __init__(self, ttl_minutes: int = 30):
           self._cache: dict[str, tuple[str, datetime]] = {}
           self._ttl = timedelta(minutes=ttl_minutes)
           self._hits = 0
           self._misses = 0

       def get(self, key: str) -> str | None: ...
       def set(self, key: str, value: str) -> None: ...

       @property
       def stats(self) -> dict: ...
   ```
2. In `analyzer.py`, create one `CodeCache` instance per run (not per error)
3. Wrap tool execution for `read_file` and `search_code`:
   ```python
   def execute_read_file(path: str, cache: CodeCache, github: GithubClient) -> str:
       cached = cache.get(f"file:{path}")
       if cached:
           return cached
       content = github.get_file_content(path)
       cache.set(f"file:{path}", content)
       return content
   ```
4. Log cache stats at end of run:
   ```
   Code cache: 23 requests, 8 hits (34.8%), 15 unique files read
   ```
5. Add cache stats to `RunReport`

**Test**: Analyze 3 errors that share common files. Verify cache hits on repeated file reads.

**Rollback**: Remove cache wrapper. Direct GitHub calls (current behavior).

---

## Phase 4: Batch Mode & Advanced Features (Day 2, Afternoon)

### Task 4.1: Message Batching for Triage

**Files**: `nightwatch/batch.py` (new), `nightwatch/__main__.py`, `nightwatch/runner.py`
**Effort**: ~2 hours

**Steps**:
1. Create `nightwatch/batch.py` with `BatchAnalyzer` class
2. Add `--batch` flag to CLI in `__main__.py`
3. Batch mode flow:
   - Fetch and rank errors (same as normal)
   - Submit all errors as a single batch request (first-pass triage only, no tools)
   - Save `batch_id` to a local file (`.nightwatch-batch-{timestamp}.json`)
   - Exit with message: `"Batch submitted. Run with --collect to retrieve results."`
4. Add `--collect` flag to CLI:
   - Read saved batch ID
   - Poll for completion
   - Parse results and continue normal pipeline (GitHub issues, Slack)
5. Batch triage prompt (no tools, just classification):
   ```
   Analyze this error and provide a quick triage:
   - Severity: critical/high/medium/low
   - Likely root cause (1-2 sentences)
   - Needs deep investigation: yes/no
   - Suggested fix category: code_bug/config/dependency/infra/unknown
   ```
6. Only run full agentic loop for errors marked "needs deep investigation"

**Test**: Submit 5 errors in batch mode. Collect results. Verify triage classifications are reasonable.

**Rollback**: Don't use `--batch` flag. Normal mode works exactly as before.

---

### Task 4.2: Enhanced Token Tracking & Reporting

**Files**: `nightwatch/models.py`, `nightwatch/runner.py`, `nightwatch/analyzer.py`
**Effort**: ~1 hour

**Steps**:
1. Expand `RunReport` with detailed token breakdown:
   ```python
   class TokenBreakdown(BaseModel):
       input_tokens: int = 0
       output_tokens: int = 0
       cache_read_tokens: int = 0
       cache_creation_tokens: int = 0
       thinking_tokens: int = 0
       cleared_tokens: int = 0  # Tokens saved by context editing

   class RunReport(BaseModel):
       # ... existing fields ...
       token_breakdown: TokenBreakdown = TokenBreakdown()
       cache_hit_rate: float = 0.0
       avg_iterations_per_error: float = 0.0
       avg_tokens_per_error: float = 0.0
       compaction_events: int = 0
       context_edit_savings: int = 0
   ```
2. In `analyzer.py`, track all token categories per iteration
3. In `runner.py`, aggregate into `RunReport`
4. Update Slack report to include efficiency metrics:
   ```
   Efficiency: 47K tokens (avg 9.4K/error) | Cache: 34% hit rate
   Context savings: 12K tokens cleared | 2 compaction events
   ```

**Test**: Run a full analysis. Verify all token categories are tracked accurately.

---

### Task 4.3: Tool Result Truncation

**Files**: `nightwatch/analyzer.py`
**Effort**: ~30 minutes

**Steps**:
1. Add `_truncate_tool_result(result: str, max_chars: int = 8000) -> str`
2. Apply to all tool results before appending to messages:
   ```python
   def _truncate_tool_result(result: str, max_chars: int = 8000) -> str:
       if len(result) <= max_chars:
           return result
       # Keep first and last portions
       half = max_chars // 2
       return (
           result[:half]
           + f"\n\n[... {len(result) - max_chars} chars truncated ...]\n\n"
           + result[-half:]
       )
   ```
3. Apply different limits per tool:
   - `read_file`: 8000 chars (large files)
   - `search_code`: 4000 chars (many results)
   - `list_directory`: 2000 chars (directory listings)
   - `get_error_traces`: 4000 chars (trace data)
4. Log truncation events

**Test**: Mock a large file read (>8000 chars). Verify truncation preserves beginning and end.

---

## Phase 5: Validation & Tuning (Day 3)

### Task 5.1: A/B Comparison Run

**Effort**: ~2 hours

**Steps**:
1. Run NightWatch on the same set of errors **before** and **after** optimizations
2. Compare:
   - Total tokens used
   - Average tokens per error
   - Analysis quality (root cause accuracy, fix confidence)
   - Run duration
   - Number of iterations per error
3. Document results in `openspec/context-efficiency/results.md`

### Task 5.2: Tune Thresholds

**Effort**: ~1 hour

Based on A/B results, adjust:
- Token budget per error (30K may be too generous or too tight)
- Context editing trigger (30K input tokens)
- Compaction trigger (50K input tokens)
- Tool result truncation limits
- Thinking budget decay curve
- Number of prior error summaries to include

### Task 5.3: Update Documentation

**Effort**: ~30 minutes

- Update `README.md` with new environment variables
- Update `.env.example` with new optional settings
- Add efficiency section to README

---

## Implementation Order (Critical Path)

```
Day 1 Morning:
  1.1 Token Budgeting ──┐
  1.2 Adaptive Iterations ├── All independent, can parallelize
  1.3 Adaptive Thinking ──┘

Day 1 Afternoon:
  2.1 Context Editing (clear tools + thinking) ──→ 2.2 Server-Side Compaction ──→ 2.3 Remove Manual Compression

Day 2 Morning:
  3.1 Cross-Error Context ──┐
  3.2 Code Cache ────────────┘  Independent

Day 2 Afternoon:
  4.1 Batch Mode ──────────────┐
  4.2 Enhanced Token Tracking ──┤  Independent
  4.3 Tool Result Truncation ───┘

Day 3:
  5.1 A/B Comparison ──→ 5.2 Tune Thresholds ──→ 5.3 Documentation
```

---

## New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NIGHTWATCH_TOKEN_BUDGET_PER_ERROR` | `30000` | Max tokens per error analysis |
| `NIGHTWATCH_TOTAL_TOKEN_BUDGET` | `200000` | Max tokens per run |
| `NIGHTWATCH_USE_COMPACTION` | `false` | Enable server-side compaction (Opus only) |
| `NIGHTWATCH_BATCH_MODE` | `false` | Use Message Batching API (50% cost savings) |

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `nightwatch/analyzer.py` | Context editing, compaction, token budgeting, adaptive iterations/thinking, tool truncation, code cache integration |
| `nightwatch/config.py` | New settings for budgets, compaction, batch mode |
| `nightwatch/models.py` | `TokenBreakdown` model, expanded `RunReport` |
| `nightwatch/runner.py` | Cross-error context, code cache lifecycle, enhanced reporting |
| `nightwatch/prompts.py` | System prompt update for cross-error awareness |
| `nightwatch/github.py` | `CodeCache` class |
| `nightwatch/batch.py` | New file — `BatchAnalyzer` for batch mode |
| `nightwatch/__main__.py` | `--batch` and `--collect` CLI flags |

---

## Definition of Done

- [ ] All Phase 1-4 tasks implemented
- [ ] Token usage reduced by >=40% on test run
- [ ] Analysis quality maintained (no regression in fix confidence)
- [ ] All new settings documented in `.env.example`
- [ ] Existing tests pass
- [ ] New tests for token budgeting, adaptive iterations, cache
- [ ] A/B comparison documented
