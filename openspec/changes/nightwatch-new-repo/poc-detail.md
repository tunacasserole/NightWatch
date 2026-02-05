# NightsWatch POC — Detailed Execution Flow

## Scope: Error Report + Issue Creation

**What you do**: Run a script.
**What happens**: NightsWatch queries New Relic, groups/ranks errors, runs Claude analysis on the top ones, DMs you a rich report in Slack, then picks the top 3 most actionable errors and creates GitHub issues for them (if no duplicate exists).

---

## How You Run It

```bash
# From the nightswatch repo directory
./venv/bin/python -m nightswatch

# Or with options
./venv/bin/python -m nightswatch --since 24h --max-errors 5 --verbose
```

That's it. It runs, does its work, prints progress to console, DMs you the report, exits.

---

## Step-by-Step Execution Flow

### Step 1: Boot & Config

```
nightswatch/__main__.py
```

- Parse CLI args (`--since`, `--max-errors`, `--verbose`, `--dry-run`)
- Load `.env` via python-dotenv
- Validate all required env vars are set (fail fast with clear error if not)
- Print banner: `🌙 NightsWatch starting — looking back 24h for errors...`

**Env vars needed for POC**:
```env
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...                # For code reading tools
GITHUB_REPO=g2crowd/ue              # Target repo
NEW_RELIC_API_KEY=NRAK-...
NEW_RELIC_ACCOUNT_ID=12345
SLACK_BOT_TOKEN=xoxb-...            # Bot token (not webhook URL)
SLACK_NOTIFY_USER=AA-Ron            # Your Slack display name
NIGHTWATCH_MODEL=claude-sonnet-4-5-20250929  # Optional, has default
```

### Step 2: Query New Relic for Errors

```
nightswatch/newrelic.py → fetch_errors(since="24h")
```

**What it does**: Fires a single NRQL query via GraphQL to get all TransactionErrors in the time window.

**The NRQL query** (this is the key new query TheFixer doesn't have — it fetches ALL errors in a time window, grouped):

```sql
SELECT count(*) AS occurrences,
       latest(error.class) AS error_class,
       latest(error.message) AS error_message,
       latest(transactionName) AS transaction,
       latest(path) AS http_path,
       latest(host) AS host,
       latest(entityGuid) AS entity_guid,
       latest(timestamp) AS last_seen
FROM TransactionError
WHERE appName = '{app_name}'
SINCE {since}
FACET error.class, transactionName
LIMIT 50
```

**What this gives us**: Errors grouped by `(error_class, transactionName)` with occurrence counts. One row per unique error type, not one row per occurrence.

**GraphQL wrapper** (ported from TheFixer's `newrelic_service.py`, converted to sync):

```python
import httpx

class NewRelicClient:
    BASE_URL = "https://api.newrelic.com/graphql"

    def __init__(self, api_key: str, account_id: str):
        self.client = httpx.Client(
            headers={"Api-Key": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )
        self.account_id = account_id

    def query_nrql(self, nrql: str) -> list[dict]:
        """Execute NRQL query and return results."""
        graphql = f'''{{
          actor {{
            account(id: {self.account_id}) {{
              nrql(query: "{nrql}") {{
                results
              }}
            }}
          }}
        }}'''
        response = self.client.post(self.BASE_URL, json={"query": graphql})
        response.raise_for_status()
        data = response.json()
        return (data.get("data", {})
                    .get("actor", {})
                    .get("account", {})
                    .get("nrql", {})
                    .get("results", []))
```

**Key difference from TheFixer**: TheFixer queries errors for a specific alert that just fired. NightsWatch queries ALL errors in a time window. This is the pull-not-push model.

**Console output**:
```
🔍 Querying New Relic for errors in the last 24h...
   Found 23 unique error groups (847 total occurrences)
```

### Step 3: Filter & Rank Errors

```
nightswatch/newrelic.py → rank_errors(errors, ignore_patterns)
```

**Filter out known/ignorable errors** using `ignore.yml`:

```yaml
# ignore.yml
ignore:
  - pattern: "Net::ReadTimeout"
    match: contains
    reason: "Transient external service timeout"
  - pattern: "Rack::Timeout"
    match: contains
    reason: "Long-running request timeout, tracked separately"
  - pattern: "ActiveRecord::ConnectionTimeoutError"
    match: contains
    reason: "Connection pool exhaustion, self-resolving"
```

**Rank remaining errors by impact score**:

```python
@dataclass
class ErrorGroup:
    error_class: str
    transaction: str
    message: str
    occurrences: int
    last_seen: str
    http_path: str
    entity_guid: str | None
    score: float = 0.0

def rank_errors(errors: list[ErrorGroup]) -> list[ErrorGroup]:
    for error in errors:
        error.score = (
            min(error.occurrences / 100, 1.0) * 0.4 +       # Frequency (capped)
            severity_weight(error.error_class) * 0.3 +        # Error severity
            recency_weight(error.last_seen) * 0.2 +           # How recent
            user_facing_weight(error.transaction) * 0.1        # User-facing?
        )
    return sorted(errors, key=lambda e: e.score, reverse=True)
```

**Severity weights** (ported from TheFixer's error classification instincts):
```python
def severity_weight(error_class: str) -> float:
    """Weight errors by likely severity."""
    critical = ["SystemStackError", "NoMemoryError", "SecurityError"]
    high = ["NoMethodError", "NameError", "TypeError", "ActiveRecord::RecordNotFound"]
    medium = ["ArgumentError", "KeyError", "RuntimeError"]
    low = ["NotAuthorizedError", "CanCan::AccessDenied"]

    if any(c in error_class for c in critical): return 1.0
    if any(c in error_class for c in high): return 0.7
    if any(c in error_class for c in medium): return 0.5
    if any(c in error_class for c in low): return 0.3
    return 0.5  # Unknown = medium
```

**Pick top N** (default 5, configurable via `--max-errors`).

**Console output**:
```
📊 Ranking errors by impact...
   Filtered 3 known/ignored errors
   Top 5 errors selected for analysis:
   1. NoMethodError in ProductsController#show (142 occurrences) — score: 0.87
   2. ActiveRecord::RecordNotFound in OrdersController#update (89 occurrences) — score: 0.74
   3. Redis::TimeoutError in CacheService#fetch (67 occurrences) — score: 0.61
   4. ArgumentError in Api::V3::ReviewsController#create (34 occurrences) — score: 0.52
   5. ActionView::Template::Error in layouts/application (12 occurrences) — score: 0.41
```

### Step 4: Fetch Detailed Traces for Each Error

```
nightswatch/newrelic.py → fetch_traces_for_error(error_group)
```

For each of the top N errors, fetch detailed stack traces. This is the same query pattern TheFixer uses in `fetch_error_traces()`, but targeted at specific error classes:

```sql
SELECT *
FROM TransactionError
WHERE appName = '{app_name}'
  AND error.class = '{error_class}'
  AND transactionName = '{transaction}'
SINCE {since}
LIMIT 5
```

Plus the ErrorTrace query for stack traces:
```sql
SELECT *
FROM ErrorTrace
WHERE appName = '{app_name}'
  AND error.class = '{error_class}'
SINCE {since}
LIMIT 3
```

This gives Claude actual stack traces to work with, not just error class + message.

**Console output**:
```
📋 Fetching detailed traces for top 5 errors...
   [1/5] NoMethodError — 5 transaction errors, 3 stack traces
   [2/5] RecordNotFound — 5 transaction errors, 2 stack traces
   ...
```

### Step 5: Claude Agentic Analysis (Per Error)

```
nightswatch/analyzer.py → analyze_error(error_group, traces)
```

**This is the core.** Ported directly from TheFixer's `claude_service.py` agentic loop, but:
- Sync `Anthropic()` instead of `AsyncAnthropic()`
- No vector memory lookup
- No two-phase split
- One thorough pass (up to 15 iterations)
- Prompt caching for system prompt + tools
- `time.sleep()` instead of `asyncio.sleep()` between iterations

**The agentic loop** (simplified from TheFixer):

```python
from anthropic import Anthropic

client = Anthropic()

def analyze_error(error: ErrorGroup, traces: dict, config: Config) -> Analysis:
    """Run Claude agentic loop to analyze a single error."""

    # Build the initial message with error context + trace summary
    message = build_analysis_prompt(error, traces)
    messages = [{"role": "user", "content": message}]

    iteration = 0
    max_iterations = calculate_max_iterations(error.error_class)

    while iteration < max_iterations:
        iteration += 1
        if iteration > 1:
            time.sleep(1.5)  # Rate limit protection

        response = call_claude_with_retry(
            client=client,
            model=config.model,
            system=SYSTEM_PROMPT,      # Cached across all errors in this run
            tools=TOOLS,               # Cached across all errors in this run
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_results = execute_tools(response.content)
            messages.append({"role": "assistant", "content": serialize_content(response.content)})
            messages.append({"role": "user", "content": tool_results})

            # Compress conversation if getting long
            if iteration > 6 and len(messages) > 8:
                messages = compress_conversation(messages)
        else:
            # Done — parse the structured output
            return parse_analysis(response)

    # Hit limit — return partial analysis
    return Analysis(
        title=f"{error.error_class} in {error.transaction}",
        reasoning="Analysis incomplete — hit iteration limit",
        has_fix=False,
        confidence="low",
    )
```

**Tools available to Claude** (same 4 as TheFixer):

| Tool | Implementation | Source |
|------|---------------|--------|
| `read_file(path)` | `github.repo.get_contents(path).decoded_content` | TheFixer's `github_service.py` |
| `search_code(query)` | `github.search_code(query, repo=repo)` | TheFixer's `github_service.py` |
| `list_directory(path)` | `github.repo.get_contents(path)` → names/types | TheFixer's `github_service.py` |
| `get_error_traces(limit)` | Returns the pre-fetched trace data | TheFixer's `newrelic_service.py` |

**Prompt caching** (new — not in TheFixer):

```python
response = client.messages.create(
    model=model,
    max_tokens=8192,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}
    }],
    tools=TOOLS,  # Anthropic caches tools automatically
    messages=messages,
)
```

When analyzing 5 errors in sequence, the system prompt + tool definitions are cached after the first call. Saves ~2K input tokens per subsequent error.

**Console output** (per error):
```
🤖 Analyzing error 1/5: NoMethodError in ProductsController#show
   Iteration 1: search_code("ProductsController")
   Iteration 2: read_file("app/controllers/products_controller.rb")
   Iteration 3: search_code("Product.find_by")
   Iteration 4: read_file("app/models/product.rb")
   Iteration 5: Analysis complete (4 iterations, 3,847 tokens)
   ✅ Fix found — confidence: high
```

### Step 6: Build the Report

```
nightswatch/runner.py → build_report(results)
```

After all errors are analyzed, build a structured report:

```python
@dataclass
class RunReport:
    """Summary of a NightsWatch run."""
    timestamp: str
    lookback_hours: int
    total_errors_found: int
    errors_filtered: int
    errors_analyzed: int
    analyses: list[ErrorAnalysisResult]  # Each has: error + analysis
    total_tokens_used: int
    total_api_calls: int
    run_duration_seconds: float

    @property
    def fixes_found(self) -> int:
        return sum(1 for a in self.analyses if a.analysis.has_fix)

    @property
    def high_confidence(self) -> int:
        return sum(1 for a in self.analyses
                   if a.analysis.has_fix and a.analysis.confidence == "high")
```

### Step 7: Slack DM the Report

```
nightswatch/slack.py → send_report_dm(report)
```

**Ported from TheFixer's `slack_service.py`** — same pattern:
1. `WebClient(token=bot_token)` (sync, not async)
2. `users_list()` → find user by display name
3. `conversations_open(users=[user_id])` → get DM channel
4. `chat_postMessage(channel=channel_id, blocks=blocks)` → send rich message

**The Slack message** (Block Kit):

```
┌──────────────────────────────────────────────┐
│  🌙 NightsWatch Daily Report                  │
│  Feb 5, 2026 · Last 24 hours                │
├──────────────────────────────────────────────┤
│  📊 23 error groups · 847 occurrences        │
│  🔍 5 analyzed · 2 fixes found              │
├──────────────────────────────────────────────┤
│                                              │
│  1. 🟢 NoMethodError                         │
│     ProductsController#show · 142 occ.      │
│     Fix: Add nil check on product.vendor     │
│     Confidence: HIGH                         │
│                                              │
│  2. ⚠️ ActiveRecord::RecordNotFound          │
│     OrdersController#update · 89 occ.       │
│     Needs investigation: order soft-deleted  │
│     before update callback fires             │
│     Confidence: MEDIUM                       │
│                                              │
│  3. 🔴 Redis::TimeoutError                   │
│     CacheService#fetch · 67 occ.            │
│     External service timeout, likely         │
│     transient. Consider retry logic.         │
│     Confidence: LOW                          │
│                                              │
│  4. ⚠️ ArgumentError                         │
│     Api::V3::ReviewsController#create        │
│     Invalid date format from mobile client   │
│     Confidence: MEDIUM                       │
│                                              │
│  5. 🔴 ActionView::Template::Error           │
│     layouts/application · 12 occ.           │
│     Partial rendering nil object. Needs      │
│     manual investigation.                    │
│     Confidence: LOW                          │
│                                              │
├──────────────────────────────────────────────┤
│  ⏱ Completed in 4m 23s · 12 API calls       │
│  📊 28,451 tokens used                       │
└──────────────────────────────────────────────┘
```

**Slack Block Kit structure** (simplified from TheFixer's per-error notifications into one report):

```python
def build_report_blocks(report: RunReport) -> list[dict]:
    blocks = [
        # Header
        {"type": "header", "text": {"type": "plain_text", "text": "🌙 NightsWatch Daily Report"}},
        # Summary stats
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Errors Found:* {report.total_errors_found} groups"},
            {"type": "mrkdwn", "text": f"*Analyzed:* {report.errors_analyzed}"},
            {"type": "mrkdwn", "text": f"*Fixes Found:* {report.fixes_found}"},
            {"type": "mrkdwn", "text": f"*Duration:* {report.run_duration_seconds:.0f}s"},
        ]},
        {"type": "divider"},
    ]

    # One section per analyzed error
    for i, result in enumerate(report.analyses, 1):
        error = result.error
        analysis = result.analysis
        emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(analysis.confidence, "⚪")

        status = "Fix found" if analysis.has_fix else "Needs investigation"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{i}. {emoji} {error.error_class}*\n"
            f"`{error.transaction}` · {error.occurrences} occurrences\n"
            f"{analysis.reasoning[:200]}{'...' if len(analysis.reasoning) > 200 else ''}\n"
            f"Confidence: *{analysis.confidence.upper()}* · {status}"
        )}})

    # Footer
    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": (
            f"⏱ {report.run_duration_seconds:.0f}s · "
            f"{report.total_api_calls} API calls · "
            f"{report.total_tokens_used:,} tokens"
        )}
    ]})

    return blocks
```

### Step 8: Select Top N for GitHub Issues

```
nightswatch/runner.py → select_for_issues(analyses, max_issues=3)
```

After ALL errors are analyzed and the Slack report is sent, NightsWatch selects the top candidates for GitHub issue creation. The selection criteria are different from the error ranking — here we're optimizing for **actionable issues where Claude actually understood the problem**.

**Selection scoring** (not the same as error ranking):

```python
def select_for_issues(analyses: list[ErrorAnalysisResult], max_issues: int = 3) -> list[ErrorAnalysisResult]:
    """Pick the top N errors most likely to produce useful GitHub issues.

    Prioritizes errors where Claude has:
    - High/medium confidence (understood the problem)
    - A concrete fix OR clear actionable next steps
    - Higher occurrence count (more impactful)
    """
    candidates = []
    for result in analyses:
        a = result.analysis

        # Skip low-confidence, vague analyses — they make bad issues
        if a.confidence == "low" and not a.has_fix:
            continue

        score = 0.0

        # Confidence is king — we want issues where Claude understood the problem
        if a.confidence == "high": score += 0.5
        elif a.confidence == "medium": score += 0.3

        # Has a fix? Even better — the issue is already actionable
        if a.has_fix: score += 0.3

        # More occurrences = higher impact
        score += min(result.error.occurrences / 200, 0.2)

        result.issue_score = score
        candidates.append(result)

    return sorted(candidates, key=lambda r: r.issue_score, reverse=True)[:max_issues]
```

**Why this is separate from error ranking**: Error ranking (Step 3) picks the most *impactful* errors to analyze. Issue selection (Step 8) picks the most *actionable* analyses to create issues for. An error can be very frequent but if Claude returned a vague "needs investigation" with low confidence, it doesn't make a good issue.

**Configurable**: `--max-issues N` (default 3). Set to 0 to skip issue creation entirely (report-only mode).

**Console output**:
```
🎯 Selecting top 3 errors for GitHub issues...
   1. NoMethodError in ProductsController#show — confidence: high, has_fix: true (score: 0.94)
   2. ArgumentError in Api::V3::ReviewsController#create — confidence: medium, has_fix: true (score: 0.68)
   3. ActiveRecord::RecordNotFound in OrdersController#update — confidence: medium, has_fix: false (score: 0.52)
   ⏭️  Skipped: Redis::TimeoutError (low confidence, no fix)
   ⏭️  Skipped: ActionView::Template::Error (low confidence, no fix)
```

### Step 9: Deduplicate Against Existing GitHub Issues

```
nightswatch/github.py → find_existing_issue(error_class, transaction)
```

**Ported directly from TheFixer's `find_existing_issue()`** — same multi-level matching strategy:

```python
def find_existing_issue(
    self,
    error_class: str,
    transaction_name: str,
) -> Issue | None:
    """Find an existing open issue for the same error.

    Multi-level matching strategy (ported from TheFixer):
    1. Best match: error_class + transaction_name in title/body
    2. Good match: error_class only
    3. Fallback: transaction_name only
    """
    # If we have nothing to match on, skip
    if not error_class and not transaction_name:
        return None

    # Search open issues with nightswatch label
    open_issues = self.repo.get_issues(state="open", labels=["nightswatch"])

    error_class_lower = error_class.lower() if error_class else None
    transaction_lower = transaction_name.lower() if transaction_name else None

    # Extract action from transaction (e.g., "products/show" from "Controller/products/show")
    action_name = None
    if transaction_name:
        parts = transaction_name.split("/")
        if len(parts) >= 2:
            action_name = "/".join(parts[-2:]).lower()

    best_match = None
    good_match = None

    for issue in open_issues:
        combined = (issue.title + " " + (issue.body or "")).lower()

        has_error_class = error_class_lower and error_class_lower in combined
        has_transaction = transaction_lower and transaction_lower in combined
        has_action = action_name and action_name in combined

        # Best: both error_class AND transaction
        if has_error_class and (has_transaction or has_action):
            return issue  # Exact match, return immediately

        # Good: just error_class
        if has_error_class and not good_match:
            good_match = issue

        # Fallback: just transaction/action
        if (has_transaction or has_action) and not best_match:
            best_match = issue

    return good_match or best_match
```

**Key behavior**: This searches open issues with the `nightswatch` label (not `thefixer`). It looks at both title AND body text, so even if the title is short, the error details in the issue body will match.

**For each candidate**:

```python
for result in selected_for_issues:
    existing = github.find_existing_issue(
        error_class=result.error.error_class,
        transaction_name=result.error.transaction,
    )

    if existing:
        # Don't create duplicate — add occurrence comment instead
        github.add_occurrence_comment(
            issue=existing,
            error=result.error,
            analysis_summary=result.analysis.reasoning[:300],
        )
        logger.info(f"Duplicate found: issue #{existing.number} — added occurrence comment")
    else:
        # Create new issue
        issue = github.create_issue(result.error, result.analysis)
        logger.info(f"Created issue #{issue['number']}")
```

**Console output**:
```
🔍 Checking for duplicate issues...
   [1/3] NoMethodError in ProductsController#show
         → No existing issue found. Creating new issue...
         ✅ Created issue #1205: "NoMethodError in products/show: undefined method `vendor_name`"
   [2/3] ArgumentError in Api::V3::ReviewsController#create
         → No existing issue found. Creating new issue...
         ✅ Created issue #1206: "ArgumentError in reviews/create: invalid date format"
   [3/3] ActiveRecord::RecordNotFound in OrdersController#update
         → Found existing issue #1198 (matched on error_class + transaction)
         💬 Added occurrence comment to issue #1198 (occurrence #3)
```

### Step 10: WIP Limits Check

```
nightswatch/github.py → check_wip_limits()
```

**Ported from TheFixer's `get_open_thefixer_issue_count()`**. Before creating issues, check we're not flooding the repo:

```python
MAX_OPEN_ISSUES = 10  # Configurable via NIGHTWATCH_MAX_OPEN_ISSUES

def check_wip_limits(self) -> tuple[bool, int]:
    """Check if we're under the open issue limit.

    Returns:
        (can_create, current_count)
    """
    open_issues = self.repo.get_issues(state="open", labels=["nightswatch"])
    count = sum(1 for _ in open_issues)

    can_create = count < MAX_OPEN_ISSUES
    if not can_create:
        logger.warning(f"WIP limit reached: {count}/{MAX_OPEN_ISSUES} open nightswatch issues")

    return can_create, count
```

**If WIP limit reached**: Skip issue creation, still send the Slack report with a note: "⚠️ Issue creation skipped — {count} open issues already exist. Review and close existing issues first."

This prevents NightsWatch from piling up 50 unreviewed issues.

### Step 11: Create GitHub Issues

```
nightswatch/github.py → create_issue(error, analysis)
```

**Ported from TheFixer's `create_issue()` and `_build_issue_body()`** with NightsWatch branding:

**Issue title** (same logic as TheFixer's `_build_issue_title()`):
```
NoMethodError in products/show: undefined method `vendor_name`
```

**Issue labels**:
- `nightswatch` — all NightsWatch issues (replaces `thefixer`)
- `has-fix` — Claude identified a concrete fix
- `needs-investigation` — Claude analyzed but no confident fix
- Confidence label: `confidence:high`, `confidence:medium`

**Issue body** (adapted from TheFixer's `_build_issue_body()`):

```markdown
## Error Details

- **Exception**: `NoMethodError`
- **Location**: `Controller/products/show`
- **Message**: undefined method `vendor_name` for nil:NilClass
- **Occurrences**: 142 in the last 24h

## Links

🔍 **[View Error in New Relic](https://one.newrelic.com/nr1-core/errors-inbox/entity/...)**

## Analysis

The `ProductsController#show` action calls `@product.vendor.vendor_name` on line 47
of `app/controllers/products_controller.rb`. When a product has no associated vendor
(vendor_id is nil), `@product.vendor` returns nil, and calling `.vendor_name` on nil
raises NoMethodError.

The fix is to add a nil check using the safe navigation operator (`&.`) or provide
a default value.

## Proposed Fix

- `app/controllers/products_controller.rb`: modify

<details>
<summary>View proposed changes</summary>

### `app/controllers/products_controller.rb` (modify)

```ruby
# Line 47: Change from:
vendor_name = @product.vendor.vendor_name
# To:
vendor_name = @product.vendor&.vendor_name || "Unknown Vendor"
```

</details>

## Next Steps

- [ ] Verify the nil check doesn't mask a data integrity issue
- [ ] Check if other actions in ProductsController have the same pattern

---
*🌙 Created by [NightsWatch](https://github.com/yourorg/nightswatch)*
```

### Step 12: Add Occurrence Comments (for Duplicates)

```
nightswatch/github.py → add_occurrence_comment(issue, error, analysis_summary)
```

**Ported from TheFixer's `add_occurrence_comment()`**. When we find a duplicate, instead of creating a new issue, we comment on the existing one:

```markdown
## 🔄 New Occurrence

| Field | Value |
|-------|-------|
| **Time** | 2026-02-05 06:00:12 UTC |
| **Occurrences** | 142 in last 24h |
| **🔍 View Error** | [Open in Errors Inbox](https://one.newrelic.com/...) |

### Quick Analysis
Same NoMethodError on product.vendor.vendor_name. 142 occurrences in the last 24h,
up from 89 when this issue was first created.

---
*🌙 Occurrence logged by [NightsWatch](https://github.com/yourorg/nightswatch)*
```

This keeps existing issues updated with fresh occurrence data without creating duplicates.

### Step 13: Update Slack Report with Issue Links

After issue creation, the Slack DM gets a follow-up message (or the original report includes them if we create issues first — but since we DM the report first as a "preview", a follow-up is cleaner):

```
📋 GitHub Issues Created:
• #1205 — NoMethodError in products/show (has-fix, high confidence)
• #1206 — ArgumentError in reviews/create (has-fix, medium confidence)
• Existing #1198 updated — RecordNotFound in orders/update (new occurrence comment)
```

### Step 14: Select Best Candidate for PR

```
nightswatch/runner.py → select_for_pr(created_issues)
```

Out of the issues we just created (not the duplicates we commented on), pick the ONE with the highest confidence and a concrete fix. This is the crown jewel of each run — one PR ready for human review in the morning.

**Selection criteria** (must meet ALL):
1. `has_fix == True` — Claude proposed actual file changes
2. `confidence == "high"` (preferred) or `"medium"` (acceptable)
3. `file_changes` list is non-empty — there's something to commit
4. Issue was newly created this run (not a duplicate we commented on)

```python
def select_for_pr(created_issues: list[CreatedIssueResult]) -> CreatedIssueResult | None:
    """Pick the single best issue to create a PR for.

    Only considers issues created THIS run (not duplicates).
    Only considers issues where Claude has a concrete fix.
    Returns the highest-confidence candidate, or None.
    """
    candidates = [
        r for r in created_issues
        if r.action == "created"           # New issue, not a duplicate comment
        and r.analysis.has_fix             # Claude has a concrete fix
        and r.analysis.file_changes        # With actual file changes
    ]

    if not candidates:
        return None

    # Sort by confidence (high > medium > low), then by occurrence count
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    candidates.sort(
        key=lambda r: (
            confidence_order.get(r.analysis.confidence, 0),
            r.error.occurrences,
        ),
        reverse=True,
    )

    best = candidates[0]

    # Only proceed if confidence is at least medium
    if best.analysis.confidence == "low":
        logger.info("Best PR candidate has low confidence — skipping PR creation")
        return None

    return best
```

**Console output**:
```
🔧 Selecting best candidate for PR...
   Best candidate: NoMethodError in products/show
   Confidence: HIGH | Fix: 1 file change | Occurrences: 142
   → Proceeding with PR creation
```

### Step 15: Create Draft PR

```
nightswatch/github.py → create_pull_request(error, analysis, issue_number)
```

**Ported from TheFixer's `create_pull_request()`, `create_branch()`, `create_or_update_file()`, and `_build_pr_body()`**. Same pattern:

1. **Create branch**: `nightswatch/fix-{error_class}-{timestamp}`
2. **Commit file changes**: Each `FileChange` from the analysis gets committed
3. **Open draft PR**: Links back to the issue

```python
def create_pull_request(
    self,
    error: ErrorGroup,
    analysis: Analysis,
    issue_number: int,
) -> dict:
    """Create a draft PR with Claude's proposed fix.

    Args:
        error: The error being fixed
        analysis: Claude's analysis with file_changes
        issue_number: The GitHub issue number (for cross-linking)

    Returns:
        Dict with PR url and number
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    # Clean error class for branch name (NoMethodError → nomethoderror)
    safe_class = error.error_class.lower().replace("::", "-").replace(" ", "-")
    branch_name = f"nightswatch/fix-{safe_class}-{timestamp}"

    # Create feature branch from base
    self.create_branch(branch_name)

    # Commit each file change
    for change in analysis.file_changes:
        if change.content:
            self.create_or_update_file(
                path=change.path,
                content=change.content,
                message=f"fix: {analysis.title}",
                branch=branch_name,
            )

    # Build PR body with issue link
    pr_body = self._build_pr_body(error, analysis, issue_number)

    # Create as DRAFT PR — requires human review
    pr = self.repo.create_pull(
        title=f"fix: {analysis.title} [NO-JIRA]",
        body=pr_body,
        head=branch_name,
        base=self.base_branch,
        draft=True,  # Always draft — human reviews in the morning
    )

    # Add comment to the issue linking to the PR
    self.repo.get_issue(issue_number).create_comment(
        f"🔧 **Draft PR created**: #{pr.number}\n\n"
        f"NightsWatch has created a draft PR with a proposed fix. "
        f"Please review and merge if appropriate."
    )

    return {"url": pr.html_url, "number": pr.number}
```

**PR body** (adapted from TheFixer's `_build_pr_body()`):

```markdown
## 🌙 NightsWatch Auto-Fix

Closes #1205

## Error Details

- **Exception**: `NoMethodError`
- **Location**: `Controller/products/show`
- **Occurrences**: 142 in the last 24h
- **🔍 [View in New Relic](https://one.newrelic.com/...)**

## Analysis

The `ProductsController#show` action calls `@product.vendor.vendor_name` on line 47.
When a product has no associated vendor (vendor_id is nil), `@product.vendor` returns
nil, causing NoMethodError.

## Changes Made

- `app/controllers/products_controller.rb`: Added nil-safe navigation operator

## Confidence

**HIGH** — Root cause clearly identified in source code. Fix is a standard Ruby
nil-safe navigation pattern.

## Testing Checklist

- [ ] Verify fix doesn't mask a data integrity issue
- [ ] Run existing ProductsController tests
- [ ] Test with a product that has no vendor

---
*🌙 This PR was automatically generated by [NightsWatch](https://github.com/yourorg/nightswatch)*
*Draft PR — requires human review before merge*
```

**Key decisions**:
- **Always draft**: Never auto-merge. Human reviews in the morning.
- **One PR per run**: Don't flood with PRs. One confident fix per day.
- **Cross-linked**: PR references the issue (`Closes #1205`), issue gets a comment linking to the PR.
- **`[NO-JIRA]`**: Same format as TheFixer for consistency in the target repo.

**Console output**:
```
🔧 Creating draft PR for NoMethodError in products/show...
   Branch: nightswatch/fix-nomethoderror-20260205060012
   Committed: app/controllers/products_controller.rb
   ✅ Created draft PR #427: "fix: NoMethodError in products/show [NO-JIRA]"
   💬 Added PR link comment to issue #1205
```

### Step 16: Final Slack Follow-Up

After issues and PR are created, send a follow-up Slack DM with the actionable items:

```
📋 NightsWatch Actions:

Issues Created:
• #1205 — NoMethodError in products/show (has-fix, high confidence)
• #1206 — ArgumentError in reviews/create (has-fix, medium confidence)
• #1198 updated — RecordNotFound in orders/update (occurrence #3)

Draft PR Ready for Review:
• PR #427 — fix: NoMethodError in products/show [NO-JIRA]
  Branch: nightswatch/fix-nomethoderror-20260205060012
  1 file changed · Confidence: HIGH
```

### Step 17: Exit

```
🌙 NightsWatch complete
   5 errors analyzed, 2 fixes found
   Report sent to @AA-Ron in Slack
   2 new issues created, 1 existing issue updated
   1 draft PR created (#427)
   Duration: 7m 45s
```

Exit code 0.

---

## Complete Pipeline Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    NightsWatch Pipeline                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. FETCH         Query NR for all errors (24h window)         │
│       ↓                                                         │
│  2. RANK          Group, filter ignore list, score by impact   │
│       ↓                                                         │
│  3. TRACE         Fetch detailed stack traces for top 5        │
│       ↓                                                         │
│  4. ANALYZE       Claude agentic loop per error (tools + code) │
│       ↓                                                         │
│  5. REPORT        DM full report to you in Slack               │
│       ↓                                                         │
│  6. SELECT        Pick top 3 most actionable for issues        │
│       ↓                                                         │
│  7. DEDUP         Check each against open nightswatch issues    │
│       ↓                                                         │
│  8. ISSUES        Create issues (or add occurrence comments)   │
│       ↓                                                         │
│  9. PR            Pick #1 highest-confidence fix, create PR    │
│       ↓                                                         │
│  10. NOTIFY       Follow-up Slack DM with issue/PR links       │
│       ↓                                                         │
│  11. EXIT                                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Configurable parameters:
  --since 24h          How far back to look for errors
  --max-errors 5       How many errors to analyze
  --max-issues 3       How many issues to create
  --max-prs 1          How many PRs to create (default 1)
  --dry-run            Analyze only, no issues/PRs
  --verbose            Detailed console output
```

---

## File Structure

```
nightswatch/
├── __main__.py        # CLI entry point — argparse + orchestration
├── config.py          # pydantic-settings from .env
├── models.py          # ErrorGroup, Analysis, FileChange, RunReport
├── analyzer.py        # Claude agentic loop (ported from TheFixer)
├── newrelic.py        # NRQL queries + error ranking
├── github.py          # Issues, PRs, dedup, code reading (Claude's tools + output)
├── slack.py           # DM report (ported from TheFixer)
├── prompts.py         # System prompt + tool definitions
├── runner.py          # Main orchestration: fetch → rank → analyze → report → issues → PR
├── .env.example
└── pyproject.toml
```

**9 Python files. ~1800 lines.**

---

## Dependencies (POC Only)

```toml
[project]
name = "nightswatch"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.77.0",    # Claude API (sync)
    "PyGithub>=2.1.0",      # GitHub API (code reading tools)
    "httpx>=0.26.0",        # New Relic GraphQL (sync)
    "slack-sdk>=3.27.0",    # Slack DMs (sync WebClient)
    "pydantic>=2.0",        # Data models
    "pydantic-settings",    # Config from env
    "python-dotenv",        # .env loading
    "certifi",              # macOS SSL fix
]
```

**8 dependencies.** No YAML parsing yet (hardcode ignore list in POC).

---

## What Gets Ported from TheFixer (Exact Functions)

### From `claude_service.py`:
| Function | Port Status | Changes |
|----------|-------------|---------|
| `SYSTEM_PROMPT` | Port + simplify | Remove two-phase references |
| `TOOLS` | Port as-is | Add `strict: true` later |
| `_call_claude_with_retry()` | Port | `async` → `sync`, `asyncio.sleep` → `time.sleep` |
| `_execute_tools()` | Port | `async` → `sync` |
| `_execute_single_tool()` | Port | `async` → `sync`, remove cache service |
| `_serialize_response_content()` | Port as-is | No changes |
| `_parse_analysis()` | Port as-is | Replace with structured outputs in Phase 1.5 |
| `_build_error_summary()` | Port as-is | No changes |
| `_summarize_traces()` | Port as-is | No changes |
| `_should_summarize_conversation()` | Port as-is | No changes |
| `_summarize_conversation()` | Port as-is | No changes |
| `_calculate_max_iterations()` | Port as-is | No changes |
| `APICallMetrics` | Port as-is | No changes |
| `analyze_alert()` | Port + modify | Remove vector memory, single pass |
| `quick_analyze_alert()` | **Skip** | No two-phase |
| `deep_research_and_update()` | **Skip** | No two-phase |
| `_adapt_past_analysis()` | **Skip** | No vector memory |
| `_store_analysis_in_memory()` | **Skip** | No vector memory |
| `_merge_analyses()` | **Skip** | No two-phase |

### From `newrelic_service.py`:
| Function | Port Status | Changes |
|----------|-------------|---------|
| `__init__()` | Port | `AsyncClient` → `Client` (sync httpx) |
| `fetch_error_traces()` | Port + modify | Takes `ErrorGroup` not `NewRelicAlert` |
| `fetch_error_details()` | Port as-is | Sync |
| **NEW** `fetch_all_errors()` | **New** | Grouped NRQL query for time window |
| **NEW** `rank_errors()` | **New** | Impact scoring algorithm |

### From `github_service.py`:
| Function | Port Status | Changes |
|----------|-------------|---------|
| `read_file()` | Port as-is | Already sync (PyGithub) |
| `search_code()` | Port as-is | Already sync |
| `list_directory()` | Port as-is | Already sync |
| `create_issue()` | Port + modify | NightsWatch labels, adapted signature |
| `_build_issue_title()` | Port as-is | Same title logic |
| `_build_issue_body()` | Port + modify | NightsWatch branding, occurrence count |
| `find_existing_issue()` | Port + modify | Search `nightswatch` label not `thefixer` |
| `add_occurrence_comment()` | Port + modify | NightsWatch branding |
| `get_open_thefixer_issue_count()` | Port + rename | `get_open_issue_count()`, `nightswatch` label |
| `create_pull_request()` | Port + modify | `draft=True`, cross-link to issue |
| `create_branch()` | Port as-is | Already sync |
| `create_or_update_file()` | Port as-is | Already sync |
| `_build_pr_body()` | Port + modify | NightsWatch branding, issue cross-link |

### From `slack_service.py`:
| Function | Port Status | Changes |
|----------|-------------|---------|
| `__init__()` | Port | `AsyncWebClient` → `WebClient` (sync) |
| `_create_ssl_context()` | Port as-is | Same macOS fix |
| `get_user_id()` | Port | `async` → `sync` |
| `open_dm_channel()` | Port | `async` → `sync` |
| `send_notification()` | Port + modify | Renamed to `send_report()`, new Block Kit layout |

### From `schemas/webhook.py`:
| Model | Port Status | Changes |
|-------|-------------|---------|
| `Analysis` | Port as-is | Core model |
| `FileChange` | Port as-is | Core model |
| `NewRelicAlert` | **Skip** | Different data model for batch |
| **NEW** `ErrorGroup` | **New** | Grouped error with count + ranking |
| **NEW** `RunReport` | **New** | Run summary for Slack report |

---

## Execution Timeline

```
0:00  Boot, load config, validate env vars
0:02  Query New Relic (1 API call, ~2 seconds)
0:05  Filter + rank errors
0:10  Fetch traces for top 5 (5 API calls, ~10 seconds)
0:20  Analyze error 1 with Claude (~4-6 iterations, ~60 seconds)
1:20  Analyze error 2 (~60 seconds)
2:20  Analyze error 3 (~60 seconds)
3:20  Analyze error 4 (~60 seconds)
4:20  Analyze error 5 (~60 seconds)
4:30  Build report, send Slack DM
4:40  Select top 3 for issues, dedup check (3 GitHub searches, ~5 seconds)
4:50  Create 2-3 GitHub issues (~10 seconds)
5:00  Select best for PR, create branch, commit, open draft PR (~15 seconds)
5:15  Follow-up Slack DM with issue/PR links
5:20  Exit
```

**~5-7 minutes total.** The analysis is the bottleneck. Issue/PR creation is fast.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Missing env var | Exit with code 1 + clear error message |
| New Relic API down | Exit with code 1 + log error |
| No errors found | DM "No errors in the last 24h" + exit 0 |
| Claude rate limited | Retry with backoff (ported from TheFixer) |
| Claude fails on one error | Log error, skip that error, continue with rest |
| All Claude calls fail | DM partial report with failures noted |
| Slack DM fails | Print report to console as fallback |
| GitHub API down (tools) | Tools return errors, Claude adapts analysis |
| GitHub API down (issues) | Log error, skip issue creation, still send report |
| Duplicate issue found | Add occurrence comment, don't create new issue |
| WIP limit reached | Skip issue creation, note in report |
| No high-confidence fix | Skip PR creation, note in report |
| PR branch creation fails | Log error, skip PR, still create issues |
| All 3 candidates are dupes | No new issues created, just occurrence comments |

---

## What Comes After v1

Once v1 proves the pipeline (report + issues + PR):

1. **Cron/launchd scheduling** — Run at 6 AM daily automatically
2. **`ignore.yml` config** — YAML file for known error patterns to skip
3. **Structured outputs** — Replace JSON parsing with Anthropic schema guarantee
4. **Extended thinking** — Deeper reasoning for complex errors
5. **PR correlation** — Include "recent PRs that may have caused this" in issues
6. **Multiple PRs** — If confidence is high enough, create more than 1 PR per run
