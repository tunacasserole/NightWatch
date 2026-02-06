# OpenSpec Proposal: Gandalf Pattern Adoption — Multi-Agent Architecture & Structured Orchestration

**ID**: GANDALF-001
**Status**: Proposed
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: Full architectural refactor — `runner.py`, `analyzer.py`, `agents.py`, `models.py`, `validation.py`, new modules
**Repository Under Review**: https://github.com/g2crowd/gandalf/pull/106
**Decision**: Adopt the *architecture patterns*, not the code (TypeScript → Python; DevOps config generation → error analysis)
**Supersedes**: None (builds on COMPOUND-002, RALPH-001)
**See Also**: [RALPH-001](../ralph-pattern-adoption/proposal.md), [COMPOUND-002](../compound-engineering-implementation/proposal.md)

---

## 1. Executive Summary

NightWatch is currently a single-agent, single-pipeline batch tool with all orchestration in one ~490-line `run()` function. It works, but it has hit its architectural ceiling:

- **No agent abstraction** — agents are config (Markdown + YAML), not behavior. Only one agent exists.
- **No orchestration layer** — 15 procedural steps in one function with no pipeline abstraction.
- **No inter-agent coordination** — no message bus, no state management, no task delegation.
- **No structured validation** — one 80-line function with ad-hoc checks.
- **Monolithic types** — all dataclasses in one `models.py` with no interfaces or protocols.

Gandalf PR #106 implements a multi-agent orchestration system with patterns that directly address every one of these limitations. The architecture is clean, well-separated, and battle-tested with 914 tests across 67 files.

**What we adopt** (8 patterns):

| # | Pattern | From Gandalf | NightWatch Adaptation |
|---|---------|-------------|----------------------|
| 1 | BaseAgent abstract class | Template Method with lifecycle | Python ABC with `execute()`, `cleanup()`, `executeWithTimeout()` |
| 2 | Typed message protocol | Generic envelope `AgentMessage<T>` | Python dataclass with `Generic[T]` |
| 3 | Agent registry | Singleton with factory method | Module-level registry with `@register_agent` decorator |
| 4 | Phase-based orchestration | 5-phase pipeline with iteration | Pipeline stages replacing the monolithic `run()` |
| 5 | Message bus | In-memory pub/sub | asyncio-compatible pub/sub with typed handlers |
| 6 | State manager | Deep-clone session store | Pydantic model with immutable snapshots |
| 7 | Layered validation | 5-layer pipeline with short-circuit | Composable validator chain for file changes + analysis quality |
| 8 | Domain-segmented types | Types organized by feature domain | Split `models.py` into `types/` package |

**What we don't adopt**:
- Gandalf's domain-specific agents (Gatherer, ConfigGenerator, etc.) — those solve DevOps config generation, not error analysis
- Gandalf's DualRepoContextService — we have our own GitHub + New Relic context
- Gandalf's AI self-review loop — we already have multi-pass (Ralph pattern)
- Gandalf's `JSON.parse(JSON.stringify())` deep-clone hack — Python has `copy.deepcopy()`
- Gandalf's dual `IMessageBus` interface design smell — we fix this from the start

**What we don't change**:
- External client interfaces (`newrelic.py`, `github.py`, `slack.py`) stay identical
- Knowledge base (`knowledge.py`) untouched — already well-designed
- Research module (`research.py`) untouched
- Observability (`observability.py`) untouched
- Configuration (`config.py`) — additive changes only

**Estimated effort**: 3-4 days across 5 phases (each independently deployable)

---

## 2. Problem Statement

### 2.1 The 490-Line God Function

`runner.py:run()` is a sequential 15-step procedural pipeline. Every concern is interleaved: client initialization, error fetching, analysis orchestration, reporting, issue creation, PR creation, notification. There is no way to:

- Test individual pipeline stages in isolation
- Add a new stage without modifying the god function
- Run stages in parallel (e.g., Slack report while creating issues)
- Retry a failed stage independently
- Swap an implementation (e.g., different analysis strategy)

### 2.2 Agents Are Config, Not Behavior

The current `AgentConfig` dataclass holds configuration (model, tokens, tools) but has no behavior. The actual agent logic lives entirely in `analyzer.py._single_pass()` — a monolithic function that handles tool dispatch, conversation management, and result parsing. This means:

- All agents must use the same analysis strategy
- No way to compose specialized agents (e.g., a research agent feeding a diagnosis agent)
- Tool dispatch is an if/elif chain, not a registry
- No lifecycle management (initialization, cleanup, timeout handling)

### 2.3 No Structured Orchestration

The pipeline has implicit phases but no explicit phase model:

```
Current (implicit):      Proposed (explicit):
─────────────────        ────────────────────
fetch errors     ──────→ INGESTION phase
rank errors      ──────→ INGESTION phase
fetch traces     ──────→ ENRICHMENT phase
search knowledge ──────→ ENRICHMENT phase
research files   ──────→ ENRICHMENT phase
analyze errors   ──────→ ANALYSIS phase (per-error)
build report     ──────→ REPORTING phase
detect patterns  ──────→ SYNTHESIS phase
send Slack       ──────→ REPORTING phase
create issues    ──────→ ACTION phase
create PRs       ──────→ ACTION phase
compound learn   ──────→ LEARNING phase
```

### 2.4 Flat Type System

All 16 data models live in one `models.py` file with no organization. There are:
- No Protocol classes or ABCs
- No generic types
- Stringly-typed fields (`pattern_type: str` with comment listing valid values)
- Mixed Pydantic/dataclass paradigm with no clear boundary
- `list[dict]` for trace data (no schema)

---

## 3. Proposal — What Changes

### 3.1 Phase 1: Type System Foundation (new `nightwatch/types/` package)

Split `models.py` into domain-segmented type modules following Gandalf's pattern:

```
nightwatch/types/
├── __init__.py          # Re-exports for backward compat
├── core.py              # Confidence, ErrorGroup, TraceData, RunContext
├── analysis.py          # Analysis, FileChange, ErrorAnalysisResult
├── agents.py            # AgentType, AgentStatus, AgentConfig, AgentResult[T]
├── orchestration.py     # ExecutionPhase, PipelineState, PhaseResult
├── messages.py          # MessageType, MessagePriority, AgentMessage[T]
├── validation.py        # ValidationSeverity, ValidationLayer, LayerResult
├── reporting.py         # RunReport, CreatedIssueResult, CreatedPRResult
└── patterns.py          # DetectedPattern, IgnoreSuggestion, CorrelatedPR
```

**Key changes**:
- All string-typed discriminators become `StrEnum` (e.g., `pattern_type: PatternType`)
- `AgentResult[T]` is a generic dataclass wrapping any agent output with confidence, timing, suggestions
- `AgentMessage[T]` is a generic dataclass with envelope fields (from_agent, to_agent, type, payload, priority)
- `PipelineState` is a Pydantic model with frozen snapshots (replaces Gandalf's deep-clone pattern)
- Backward compatibility: `nightwatch/types/__init__.py` re-exports everything `models.py` currently exports
- `models.py` becomes a thin re-export file (deprecated, removed in Phase 5)

**Migration strategy**: Add `types/` package first, update imports module-by-module, keep `models.py` as re-export shim until all consumers are migrated.

### 3.2 Phase 2: BaseAgent Abstract Class & Registry

Replace the config-only `AgentConfig` with a proper agent hierarchy:

```python
# nightwatch/agents/base.py

class BaseAgent(ABC):
    """Abstract base agent with lifecycle management."""

    def __init__(self, config: AgentConfig):
        self._config = config
        self._status: AgentStatus = AgentStatus.IDLE
        self._message_bus: MessageBus | None = None

    # --- Lifecycle (from Gandalf) ---
    def initialize(self, message_bus: MessageBus) -> None: ...
    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult: ...
    def cleanup(self) -> None: ...

    # --- Execution wrapper (from Gandalf's executeWithTimeout) ---
    async def execute_with_timeout(
        self, context: AgentContext, operation: Callable
    ) -> AgentResult: ...

    # --- Messaging (from Gandalf) ---
    def send_message(self, msg_type: MessageType, payload: Any, to: AgentType | None = None) -> None: ...
    def subscribe(self, msg_type: MessageType, handler: MessageHandler) -> str: ...
```

**Agent implementations** (NightWatch-specific, not from Gandalf):

```
nightwatch/agents/
├── base.py              # BaseAgent ABC + AgentContext
├── registry.py          # @register_agent decorator + AgentRegistry
├── error_analyzer.py    # Current _single_pass() logic → AnalyzerAgent
├── researcher.py        # Current research_error() → ResearchAgent
├── pattern_detector.py  # Current detect_patterns_with_knowledge() → PatternAgent
├── reporter.py          # Slack + GitHub issue creation → ReporterAgent
├── validator.py         # Current validate_file_changes() → ValidatorAgent
└── definitions/
    └── base-analyzer.md # Existing agent definition (now consumed by AnalyzerAgent)
```

**Key design decisions**:
- **Use `@register_agent` decorator** instead of Gandalf's singleton registry — more Pythonic, eliminates the "registry exists but isn't used" problem Gandalf has
- **Agent definitions (`.md` files) still work** — they configure `AnalyzerAgent`, not replace it
- **Async-first** — use `async def execute()` from the start (Gandalf is sync, which limits it)
- **Tool registry** — replace the if/elif dispatch chain with a `@tool` decorator and tool registry

### 3.3 Phase 3: Message Bus & State Manager

**Message Bus** (`nightwatch/orchestration/message_bus.py`):

Adopt Gandalf's in-memory pub/sub pattern but fix its design issues:

```python
class MessageBus:
    """In-memory pub/sub with typed handlers. Single interface (fixes Gandalf's dual-interface problem)."""

    def subscribe(self, agent_type: AgentType, msg_type: MessageType | None, handler: MessageHandler) -> str: ...
    def unsubscribe(self, subscription_id: str) -> None: ...
    def publish(self, message: AgentMessage) -> None: ...
    def broadcast(self, message: AgentMessage) -> None: ...
    def get_messages(self, session_id: str) -> list[AgentMessage]: ...
```

**Improvements over Gandalf**:
- Single `IMessageBus` protocol (Gandalf has two incompatible interfaces)
- `asyncio` compatible handlers
- `copy.deepcopy()` for isolation (not `JSON.parse/stringify` which loses `datetime` objects)
- Optional message persistence to knowledge base for cross-run analysis

**State Manager** (`nightwatch/orchestration/state_manager.py`):

Adopt Gandalf's session state pattern with Pydantic immutability:

```python
class PipelineState(BaseModel, frozen=True):
    """Immutable pipeline state snapshot. Create new instances for updates."""
    session_id: str
    current_phase: ExecutionPhase
    iteration_count: int
    agent_results: dict[AgentType, AgentResult]
    timestamps: PipelineTimestamps

class StateManager:
    def get_state(self, session_id: str) -> PipelineState: ...
    def update_state(self, session_id: str, **updates) -> PipelineState: ...  # Returns new frozen instance
```

**Improvements over Gandalf**:
- Frozen Pydantic models instead of deep-clone dance (Gandalf's `incrementIteration()` inconsistently mutates internal state)
- Type-safe updates via keyword arguments (not `Record<string, unknown>` state bag)

### 3.4 Phase 4: Pipeline Orchestrator

Replace `runner.py:run()` with a phase-based pipeline:

```python
# nightwatch/orchestration/pipeline.py

class Pipeline:
    """Phase-based execution pipeline with agent coordination."""

    phases = [
        Phase("INGESTION",   agents=[]),           # Fetch + rank errors
        Phase("ENRICHMENT",  agents=[ResearchAgent, KnowledgeAgent]),
        Phase("ANALYSIS",    agents=[AnalyzerAgent], per_error=True),
        Phase("SYNTHESIS",   agents=[PatternAgent]),
        Phase("REPORTING",   agents=[ReporterAgent]),
        Phase("ACTION",      agents=[ValidatorAgent, ReporterAgent]),
        Phase("LEARNING",    agents=[]),            # Compound to knowledge base
    ]

    async def execute(self, config: PipelineConfig) -> RunReport: ...
    async def execute_phase(self, phase: Phase, state: PipelineState) -> PhaseResult: ...
```

**Key architectural decisions** (adopted from Gandalf):

1. **Phase-based execution** — each phase has explicit entry/exit criteria
2. **Agent coordination via state** — agents read from and write to `PipelineState`
3. **Per-error iteration** — ANALYSIS phase runs AnalyzerAgent per error (like Gandalf's GATHERING→ANALYSIS→GENERATION→VALIDATION→REVIEW loop, but for errors instead of configs)
4. **Iteration support** — ANALYSIS phase can re-run with enriched context (Ralph pattern preserved)
5. **Fallback handling** — if pipeline fails, fall back to current simple `run()` (Gandalf's FallbackHandler pattern)
6. **Feature flag controlled** — `NIGHTWATCH_PIPELINE_V2=true` gates the new pipeline, old `run()` remains as fallback

**What stays in `runner.py`**:
- The existing `run()` function stays as-is (fallback mode)
- New `run_v2()` delegates to `Pipeline.execute()`
- Entry point logic checks feature flag and dispatches

### 3.5 Phase 5: Layered Validation

Replace the single `validate_file_changes()` function with Gandalf's layered validation pattern:

```
nightwatch/validation/
├── __init__.py
├── orchestrator.py      # ValidationOrchestrator — runs layers in sequence
├── layers/
│   ├── __init__.py
│   ├── path_safety.py   # Path traversal, absolute path checks (from current validation.py)
│   ├── content.py       # Non-empty content, suspicious length (from current validation.py)
│   ├── syntax.py        # Ruby/Python syntax validation (from current block counting)
│   ├── semantic.py      # NEW: Does the fix match the root cause? Cross-reference analysis
│   └── quality.py       # NEW: Confidence thresholds, file change count limits
```

**Adopted from Gandalf**:
- `IValidator` protocol with `validate(changes, context) → LayerResult`
- Short-circuit on path safety failure (like Gandalf's syntax short-circuit)
- `ValidationResult` aggregation with blocking errors vs. warnings
- `ValidationSeverity` enum (ERROR, WARNING, INFO)

**NightWatch-specific additions**:
- `SemanticValidator` — checks if proposed file changes are logically consistent with the root cause analysis
- `QualityValidator` — enforces confidence thresholds and file change limits before PR creation

---

## 4. What Doesn't Change

| Module | Status | Reason |
|--------|--------|--------|
| `newrelic.py` | Untouched | Clean client, well-tested |
| `github.py` | Untouched | Clean client, used as tool backend |
| `slack.py` | Minor | ReporterAgent calls existing methods |
| `correlation.py` | Untouched | Consumed by enrichment phase |
| `knowledge.py` | Untouched | Consumed by enrichment + learning phases |
| `research.py` | Wrapped | ResearchAgent wraps `research_error()` |
| `patterns.py` | Wrapped | PatternAgent wraps `detect_patterns_with_knowledge()` |
| `observability.py` | Untouched | Opik tracing continues to work |
| `health.py` | Untouched | HealthReport is additive |
| `quality.py` | Untouched | QualityTracker is additive |
| `config.py` | Additive | New feature flags, no breaking changes |
| `prompts.py` | Untouched | Consumed by AnalyzerAgent |

---

## 5. Migration Strategy

### 5.1 Incremental, Non-Breaking

Each phase is independently deployable. The system works at every intermediate state:

```
Phase 1 (types):       models.py re-exports from types/ → zero behavior change
Phase 2 (agents):      New agent classes wrap existing functions → zero behavior change
Phase 3 (bus/state):   Infrastructure ready, not yet wired → zero behavior change
Phase 4 (pipeline):    Feature-flagged run_v2() → opt-in, old run() is fallback
Phase 5 (validation):  Validators replace validate_file_changes() → same results, better structure
```

### 5.2 Feature Flag

```python
# config.py additions
nightwatch_pipeline_v2: bool = False  # Enable new pipeline architecture
nightwatch_pipeline_fallback: bool = True  # Fall back to run() on pipeline failure
```

### 5.3 Backward Compatibility

- `from nightwatch.models import Analysis` continues to work (re-export shim)
- `from nightwatch.agents import load_agent, AgentConfig` continues to work
- CLI interface (`--agent`, `--since`, `--max-errors`) unchanged
- All environment variables unchanged
- Knowledge base format unchanged

---

## 6. File Change Summary

### New Files (21)

```
nightwatch/types/__init__.py
nightwatch/types/core.py
nightwatch/types/analysis.py
nightwatch/types/agents.py
nightwatch/types/orchestration.py
nightwatch/types/messages.py
nightwatch/types/validation.py
nightwatch/types/reporting.py
nightwatch/types/patterns.py
nightwatch/agents/base.py
nightwatch/agents/registry.py
nightwatch/agents/error_analyzer.py
nightwatch/agents/researcher.py
nightwatch/agents/pattern_detector.py
nightwatch/agents/reporter.py
nightwatch/agents/validator.py
nightwatch/orchestration/__init__.py
nightwatch/orchestration/pipeline.py
nightwatch/orchestration/message_bus.py
nightwatch/orchestration/state_manager.py
nightwatch/validation/orchestrator.py
nightwatch/validation/layers/__init__.py
nightwatch/validation/layers/path_safety.py
nightwatch/validation/layers/content.py
nightwatch/validation/layers/syntax.py
nightwatch/validation/layers/semantic.py
nightwatch/validation/layers/quality.py
```

### Modified Files (5)

```
nightwatch/models.py        → Re-export shim (deprecated)
nightwatch/agents.py        → Re-export shim (deprecated, renamed to agents/_legacy.py)
nightwatch/runner.py         → Add run_v2() entry point, feature flag check
nightwatch/config.py         → Add pipeline_v2 and pipeline_fallback settings
nightwatch/validation.py     → Re-export shim (deprecated)
```

### New Test Files (~15)

```
tests/types/test_core.py
tests/types/test_agents.py
tests/types/test_messages.py
tests/agents/test_base.py
tests/agents/test_registry.py
tests/agents/test_error_analyzer.py
tests/agents/test_researcher.py
tests/orchestration/test_pipeline.py
tests/orchestration/test_message_bus.py
tests/orchestration/test_state_manager.py
tests/validation/test_orchestrator.py
tests/validation/layers/test_path_safety.py
tests/validation/layers/test_syntax.py
tests/validation/layers/test_semantic.py
tests/integration/test_pipeline_e2e.py
```

### Zero New Dependencies

All implementations use existing `pydantic`, `dataclasses`, `asyncio`, `abc`, `typing`, and stdlib.

---

## 7. Gandalf Patterns: Adopted vs. Improved vs. Skipped

### Adopted As-Is

| Pattern | Source | Why |
|---------|--------|-----|
| Template Method lifecycle | `BaseAgent.ts` | Clean separation of framework vs. agent logic |
| `executeWithTimeout()` wrapper | `BaseAgent.ts` | Every agent needs timeout + error handling |
| Message envelope with generics | `AgentMessage.ts` | Type-safe inter-agent communication |
| Factory functions for default instances | `types/agents.ts` | Reduce boilerplate in tests and initialization |
| Phase-based pipeline execution | `AgentOrchestrator.ts` | Explicit phases replace implicit procedural steps |
| Layered validation with short-circuit | `ValidationOrchestrator.ts` | Composable, testable validation |
| Stateless validators | `layers/*.ts` | No side effects, easy to test and compose |
| Domain-segmented type modules | `types/*.ts` | Organized by feature, not by layer |

### Adopted with Improvements

| Pattern | Gandalf's Approach | Our Improvement |
|---------|-------------------|-----------------|
| Agent registry | Singleton class, unused by orchestrator | `@register_agent` decorator, actually used by pipeline |
| Message bus interface | Two incompatible `IMessageBus` interfaces | Single `MessageBus` protocol from the start |
| State management | Deep-clone via `JSON.parse/stringify`, inconsistent mutation | Frozen Pydantic models, immutable snapshots |
| State typing | `Record<string, unknown>` state bag | Typed `PipelineState` with per-agent result fields |
| Agent config source | Hardcoded in each agent constructor | Markdown+YAML definitions (our existing pattern) + class defaults |
| Parallel execution | `Promise.all` for analysis phase only | `asyncio.gather` available for any phase |

### Skipped

| Pattern | Reason |
|---------|--------|
| `OrchestratorAgent` (786-line decision-maker) | Over-engineered for our use case; pipeline config handles phase transitions |
| `ReviewerAgent` (AI self-review) | We already have multi-pass (Ralph pattern) and quality gates |
| `FallbackHandler` error classification | Useful but can be added later; simple try/except is sufficient for now |
| `DualRepoContextService` | Domain-specific to Gandalf's config generation workflow |
| `GuidelinesParser` / `PatternDetector` / `StructureExplorer` | Domain-specific context services |
| Deep message serialization/deserialization | We're in-process Python, not cross-service; no serialization needed |
| `processingLock` on MessageBus | Gandalf defined it but never used it; we skip it entirely |
| Barrel exports (`base/index.ts`) | Python convention is explicit imports, not barrel files |

---

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Async migration complexity | Medium | Phase 2 agents are async-ready but Phase 4 pipeline can start sync, migrate to async later |
| Over-abstraction for single-error-analysis | Medium | Agents wrap existing functions; if abstraction hurts, unwrap |
| Test coverage regression during migration | High | Each phase adds tests before modifying behavior; CI must pass between phases |
| Feature flag complexity | Low | Only one flag (`pipeline_v2`); clean removal after stabilization |
| Import cycle risk with new `types/` package | Low | Types have no imports from service modules; dependency flows one way |

---

## 9. Success Criteria

1. **All existing tests pass** at every phase boundary
2. **Pipeline V2 produces identical results** to current `run()` for the same inputs (validated by running both and comparing `RunReport`)
3. **Each agent is independently testable** with mocked dependencies
4. **Pipeline stages can be tested in isolation** without running the full pipeline
5. **Validation layers can be composed** — add/remove/reorder without code changes to orchestrator
6. **New agent types can be added** by implementing `BaseAgent.execute()` and decorating with `@register_agent`
7. **Zero new dependencies** added to `pyproject.toml`
8. **Feature flag off = exact current behavior** with no performance regression

---

## 10. Implementation Order

| Phase | Dependencies | Deliverable | Can Ship Independently |
|-------|-------------|-------------|----------------------|
| 1. Type System | None | `nightwatch/types/` package + re-export shim | Yes |
| 2. Agent Base | Phase 1 | `nightwatch/agents/base.py`, `registry.py`, concrete agents | Yes |
| 3. Bus & State | Phase 1 | `nightwatch/orchestration/message_bus.py`, `state_manager.py` | Yes |
| 4. Pipeline | Phases 1-3 | `nightwatch/orchestration/pipeline.py` + `run_v2()` | Yes (feature-flagged) |
| 5. Validation | Phase 1 | `nightwatch/validation/` package | Yes |

Phases 1, 2, 3, and 5 can be developed in parallel. Phase 4 depends on 1-3.

---

## 11. Open Questions

1. **Async from day one?** — Gandalf is sync. Should we go async in Phase 2 or defer to Phase 4? Recommendation: define `async def execute()` in Phase 2 but run with `asyncio.run()` wrapper so non-async code still works.

2. **Message bus necessity** — Gandalf built a message bus but the orchestrator barely uses it (drives agents directly). Do we need pub/sub, or is direct invocation sufficient? Recommendation: build it (it's ~100 lines) but make it optional — pipeline can work with or without it.

3. **Agent granularity** — Should the AnalyzerAgent encapsulate the entire Claude loop, or should we decompose into PromptBuilder → ClaudeCall → ResponseParser agents? Recommendation: keep AnalyzerAgent as a coarse unit wrapping the existing loop; decompose later if needed.

4. **Knowledge base as agent?** — Should knowledge base operations (search, compound) be a KnowledgeAgent, or stay as utility functions called by the pipeline? Recommendation: stay as utilities for now — they don't have the lifecycle or state management needs that justify agent abstraction.
