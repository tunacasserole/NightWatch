# OpenSpec Proposal: GANDALF-001d — Pipeline Orchestrator

**ID**: GANDALF-001d
**Parent**: GANDALF-001 (Gandalf Pattern Adoption)
**Status**: Proposed
**Phase**: 4 of 5
**Date**: 2026-02-05
**Scope**: Phase-based execution pipeline replacing monolithic `run()`, feature-flagged
**Dependencies**: GANDALF-001a (Types), GANDALF-001b (Agents), GANDALF-001c (Bus/State)
**Estimated Effort**: 3-4 hours

---

## 1. Goal

Replace the monolithic `runner.py:run()` (~490 lines, 15 procedural steps) with a phase-based execution pipeline behind a feature flag. The pipeline orchestrates agents through 7 explicit phases, coordinated by the message bus and state manager. When the flag is off, existing `run()` is used. When on, `run_v2()` delegates to the pipeline with automatic fallback.

## 2. Problem

`runner.py:run()` is a 490-line god function with 15 interleaved concerns:
- Client initialization, error fetching, analysis, reporting, issue creation, PR creation, notification
- Cannot test individual stages in isolation
- Cannot add/remove/reorder stages without modifying the god function
- Cannot run stages in parallel
- Cannot retry a failed stage independently
- Cannot swap implementations (e.g., different analysis strategy)

The implicit phases in `run()` map directly to explicit pipeline phases:

```
Current (implicit):      Pipeline (explicit):
─────────────────        ────────────────────
fetch errors     ──────→ INGESTION
rank errors      ──────→ INGESTION
fetch traces     ──────→ ENRICHMENT
search knowledge ──────→ ENRICHMENT
research files   ──────→ ENRICHMENT
analyze errors   ──────→ ANALYSIS (per-error)
build report     ──────→ REPORTING
detect patterns  ──────→ SYNTHESIS
send Slack       ──────→ REPORTING
create issues    ──────→ ACTION
create PRs       ──────→ ACTION
compound learn   ──────→ LEARNING
```

## 3. What Changes

### 3.1 New File

**`nightwatch/orchestration/pipeline.py`** (~300 lines):

```python
@dataclass
class Phase:
    name: ExecutionPhase
    agent_types: list[AgentType] = field(default_factory=list)
    per_error: bool = False
    parallel: bool = False
    custom_handler: Callable | None = None

class Pipeline:
    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.bus = MessageBus()
        self.state_manager = StateManager()
        self._phases = self._build_phases()

    def _build_phases(self) -> list[Phase]:
        return [
            Phase(ExecutionPhase.INGESTION, custom_handler=self._run_ingestion),
            Phase(ExecutionPhase.ENRICHMENT, agent_types=[AgentType.RESEARCHER]),
            Phase(ExecutionPhase.ANALYSIS, agent_types=[AgentType.ANALYZER], per_error=True),
            Phase(ExecutionPhase.SYNTHESIS, agent_types=[AgentType.PATTERN_DETECTOR]),
            Phase(ExecutionPhase.REPORTING, agent_types=[AgentType.REPORTER]),
            Phase(ExecutionPhase.ACTION, agent_types=[AgentType.VALIDATOR, AgentType.REPORTER]),
            Phase(ExecutionPhase.LEARNING, custom_handler=self._run_learning),
        ]

    async def execute(self, **run_kwargs) -> RunReport: ...
    async def _execute_phase(self, phase_def, session_id, run_kwargs) -> PhaseResult: ...
    async def _fallback(self, run_kwargs) -> RunReport: ...
```

### 3.2 Modified Files

**`nightwatch/config.py`** (+4 lines):
```python
# Pipeline V2
nightwatch_pipeline_v2: bool = False
nightwatch_pipeline_fallback: bool = True
```

**`nightwatch/runner.py`** (+20 lines at bottom):
```python
async def _run_v2_async(**kwargs) -> RunReport:
    """Pipeline V2 entry point (async)."""
    from nightwatch.orchestration.pipeline import Pipeline, PipelineConfig
    config = PipelineConfig(dry_run=kwargs.get("dry_run", False), ...)
    pipeline = Pipeline(config=config)
    return await pipeline.execute(**kwargs)

def run_v2(**kwargs) -> RunReport:
    """Sync wrapper for Pipeline V2."""
    return asyncio.run(_run_v2_async(**kwargs))
```

**`nightwatch/__main__.py`** (~10 lines modified in `_run()`):
```python
settings = get_settings()
if settings.nightwatch_pipeline_v2:
    from nightwatch.runner import run_v2
    report = run_v2(since=args.since, max_errors=args.max_errors, ...)
else:
    report = run(since=args.since, max_errors=args.max_errors, ...)
```

### 3.3 Feature Flag Behavior

| `NIGHTWATCH_PIPELINE_V2` | `NIGHTWATCH_PIPELINE_FALLBACK` | Behavior |
|---------------------------|-------------------------------|----------|
| `false` (default) | N/A | Uses existing `run()` — zero change |
| `true` | `true` (default) | Uses pipeline; falls back to `run()` on failure |
| `true` | `false` | Uses pipeline; raises RuntimeError on failure |

### 3.4 Pipeline Phase Details

**INGESTION** (custom handler): Fetch errors from New Relic, filter, rank, fetch traces. Populates `state.errors_data`.

**ENRICHMENT** (ResearcherAgent): Pre-fetch code context, search knowledge base, correlate with recent PRs.

**ANALYSIS** (AnalyzerAgent, per_error=True): Run Claude analysis per error. This is the main work phase.

**SYNTHESIS** (PatternDetectorAgent): Cross-error pattern detection after all analyses complete.

**REPORTING** (ReporterAgent): Build RunReport, send Slack notification.

**ACTION** (ValidatorAgent + ReporterAgent): Validate file changes, create GitHub issues and PRs.

**LEARNING** (custom handler): Compound results to knowledge base.

## 4. What Doesn't Change

- Existing `run()` function stays as-is (fallback + default)
- CLI interface unchanged
- All environment variables unchanged
- Feature flag is off by default — zero behavior change in production

## 5. Tests

**`tests/orchestration/test_pipeline.py`** (~150 lines, 7 tests):
| Test | Validates |
|------|-----------|
| `test_pipeline_executes_all_phases` | All 7 phases execute in order |
| `test_pipeline_state_transitions` | State moves through INGESTION→...→COMPLETE |
| `test_pipeline_per_error_phase` | ANALYSIS phase runs agent per error |
| `test_pipeline_fallback_on_failure` | Falls back to run() when enable_fallback=True |
| `test_pipeline_raises_on_failure_no_fallback` | Raises RuntimeError when fallback disabled |
| `test_pipeline_feature_flag_off` | run_v2 not called when pipeline_v2=False |
| `test_pipeline_produces_run_report` | Output is a valid RunReport |

**`tests/integration/test_pipeline_e2e.py`** (~120 lines, 3 tests):
| Test | Validates |
|------|-----------|
| `test_pipeline_v2_matches_run_v1` | Same inputs produce equivalent RunReport |
| `test_pipeline_v2_with_dry_run` | No side effects in dry run mode |
| `test_pipeline_v2_fallback_to_v1` | On pipeline error, falls back to run() |

## 6. Validation Criteria

- [ ] Pipeline executes all 7 phases in order
- [ ] Pipeline produces a RunReport equivalent to `run()` for same inputs
- [ ] Feature flag `NIGHTWATCH_PIPELINE_V2=false` uses existing `run()`
- [ ] Feature flag `NIGHTWATCH_PIPELINE_V2=true` uses pipeline
- [ ] Fallback works: pipeline failure falls back to `run()`
- [ ] Per-error phase runs AnalyzerAgent once per error
- [ ] All existing tests pass (feature flag is off by default)
- [ ] `ruff check` passes

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Pipeline V2 produces different results than V1 | Medium | Integration test comparing V1 vs V2 output |
| Async adds complexity for sync callers | Low | `asyncio.run()` wrapper; agents can use sync internally |
| Phase 4 takes longer than estimated | Medium | Phases 1-3+5 deliver value independently |
| Custom handler phases (INGESTION, LEARNING) are complex | Medium | Extract from run() incrementally; test each |

## 8. Commit Message

```
feat(pipeline): add phase-based execution pipeline

7-phase pipeline replacing monolithic run(). Feature-flagged via
NIGHTWATCH_PIPELINE_V2. Falls back to existing run() on failure.
Per-error analysis phase runs AnalyzerAgent per error.

GANDALF-001d
```
