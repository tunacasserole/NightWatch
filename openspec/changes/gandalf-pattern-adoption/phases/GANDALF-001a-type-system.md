# OpenSpec Proposal: GANDALF-001a — Type System Foundation

**ID**: GANDALF-001a
**Parent**: GANDALF-001 (Gandalf Pattern Adoption)
**Status**: Proposed
**Phase**: 1 of 5
**Date**: 2026-02-05
**Scope**: Split monolithic `models.py` into domain-segmented `nightwatch/types/` package
**Dependencies**: None (foundational — all other phases depend on this)
**Estimated Effort**: 2-3 hours

---

## 1. Goal

Split the monolithic `nightwatch/models.py` (287 lines, 17 dataclasses/models) into a domain-segmented `nightwatch/types/` package with 8 modules. Zero behavior change — pure structural refactor with backward-compatible re-export shim.

## 2. Problem

All 17 data models live in one `models.py` with no organization:
- No Protocol classes or ABCs for agent/validation interfaces
- No generic types (`AgentResult[T]`, `AgentMessage[T]`)
- Stringly-typed fields (`pattern_type: str`, `match: str`) instead of enums
- Mixed Pydantic BaseModel and dataclass paradigm with no clear boundary
- No types for the agent system, message bus, orchestration, or validation layers needed by later phases

## 3. What Changes

### 3.1 New Package Structure

```
nightwatch/types/
├── __init__.py          # Re-exports everything for backward compat
├── core.py              # Confidence, ErrorGroup, TraceData, RunContext + new PatternType, MatchType enums
├── analysis.py          # Analysis, FileChange, ErrorAnalysisResult, TokenBreakdown, FileValidationResult
├── agents.py            # NEW: AgentType, AgentStatus, AgentConfig, AgentResult[T], AgentContext
├── messages.py          # NEW: MessageType, MessagePriority, AgentMessage[T], factories
├── orchestration.py     # NEW: ExecutionPhase, PipelineState, PipelineTimestamps, PhaseResult, PipelineConfig
├── validation.py        # NEW: ValidationSeverity, ValidationLayer, ValidationIssue, LayerResult, IValidator
├── reporting.py         # CreatedIssueResult, CreatedPRResult, RunReport (moved from models.py)
└── patterns.py          # DetectedPattern, IgnoreSuggestion, CorrelatedPR, PriorAnalysis (moved)
```

### 3.2 Types Moved (from models.py)

| Type | Source | Destination | Changes |
|------|--------|------------|---------|
| `Confidence` | models.py:14 | types/core.py | None |
| `ErrorGroup` | models.py:47 | types/core.py | None |
| `TraceData` | models.py:63 | types/core.py | None |
| `RunContext` | models.py:71 | types/core.py | None |
| `FileValidationResult` | models.py:126 | types/analysis.py | None |
| `TokenBreakdown` | models.py:135 | types/analysis.py | None |
| `FileChange` | models.py:23 | types/analysis.py | None |
| `Analysis` | models.py:33 | types/analysis.py | None |
| `ErrorAnalysisResult` | models.py:167 | types/analysis.py | None |
| `CreatedIssueResult` | models.py:184 | types/reporting.py | None |
| `CreatedPRResult` | models.py:196 | types/reporting.py | None |
| `RunReport` | models.py:257 | types/reporting.py | None |
| `DetectedPattern` | models.py:234 | types/patterns.py | `pattern_type: str` → `pattern_type: PatternType` |
| `IgnoreSuggestion` | models.py:247 | types/patterns.py | `match: str` → `match: MatchType` |
| `CorrelatedPR` | models.py:207 | types/patterns.py | None |
| `PriorAnalysis` | models.py:219 | types/patterns.py | None |

### 3.3 New Types (for later phases)

**core.py** — New enums:
- `PatternType(StrEnum)`: `RECURRING_ERROR`, `SYSTEMIC_ISSUE`, `TRANSIENT_NOISE`
- `MatchType(StrEnum)`: `CONTAINS`, `EXACT`, `PREFIX`

**agents.py** — Agent framework types:
- `AgentType(StrEnum)`: `ANALYZER`, `RESEARCHER`, `PATTERN_DETECTOR`, `REPORTER`, `VALIDATOR`
- `AgentStatus(StrEnum)`: `IDLE`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED`
- `AgentConfig(dataclass)`: Name, model, thinking_budget, max_tokens, tools, etc.
- `AgentResult[T](dataclass, Generic[T])`: Generic result wrapper with confidence, timing, suggestions
- `AgentContext(dataclass)`: Execution context with session_id, run_id, agent_state

**messages.py** — Inter-agent communication:
- `MessageType(StrEnum)`: Task lifecycle + data flow + control messages
- `MessagePriority(IntEnum)`: HIGH=0, MEDIUM=1, LOW=2
- `AgentMessage[T](dataclass, Generic[T])`: Typed message envelope
- Factory + classification helpers

**orchestration.py** — Pipeline types:
- `ExecutionPhase(StrEnum)`: INGESTION through COMPLETE
- `PipelineTimestamps(BaseModel, frozen=True)`: Immutable timestamps
- `PipelineState(BaseModel, frozen=True)`: Immutable pipeline state snapshot
- `PhaseResult(dataclass)`: Result of a single pipeline phase
- `PipelineConfig(dataclass)`: Pipeline configuration

**validation.py** — Validation layer types:
- `ValidationSeverity(StrEnum)`: ERROR, WARNING, INFO
- `ValidationLayer(StrEnum)`: PATH_SAFETY, CONTENT, SYNTAX, SEMANTIC, QUALITY
- `ValidationIssue(dataclass)`: Single validation finding
- `LayerResult(dataclass)`: Result from one validation layer
- `ValidationResult(dataclass)`: Aggregated result across all layers
- `IValidator(Protocol)`: Protocol for validation layers

### 3.4 Backward Compatibility

**`nightwatch/types/__init__.py`** re-exports all moved types + new types with `__all__`.

**`nightwatch/models.py`** becomes a thin re-export shim:
```python
"""Legacy re-export shim — import from nightwatch.types instead."""
from nightwatch.types.core import *       # noqa: F401, F403
from nightwatch.types.analysis import *   # noqa: F401, F403
from nightwatch.types.reporting import *  # noqa: F401, F403
from nightwatch.types.patterns import *   # noqa: F401, F403
```

All existing `from nightwatch.models import X` statements continue to work unchanged.

## 4. What Doesn't Change

- All 17 existing type definitions preserve identical fields and behavior
- All consumer code (runner.py, analyzer.py, validation.py, etc.) continues working via re-export
- No new dependencies added
- `DetectedPattern.pattern_type` and `IgnoreSuggestion.match` accept both new StrEnum values and plain strings (StrEnum inherits from str)

## 5. Tests

### New Test Files

**`tests/types/test_core.py`** (~80 lines, 8 tests):
| Test | Validates |
|------|-----------|
| `test_confidence_enum_values` | HIGH, MEDIUM, LOW string values |
| `test_pattern_type_enum_values` | All 3 PatternType values |
| `test_match_type_enum_values` | CONTAINS, EXACT, PREFIX |
| `test_error_group_defaults` | score=0.0, entity_guid=None |
| `test_run_context_to_prompt_section` | Non-empty output with entries |
| `test_run_context_to_prompt_section_empty` | Empty string when no data |
| `test_run_context_truncation` | Output respects max_chars |
| `test_run_context_record_analysis` | Appends to errors_analyzed |

**`tests/types/test_agents.py`** (~70 lines, 7 tests):
| Test | Validates |
|------|-----------|
| `test_agent_type_enum_values` | All 5 agent types |
| `test_agent_status_enum_values` | All 5 statuses |
| `test_agent_config_defaults` | model, thinking_budget, max_tokens defaults |
| `test_agent_result_success` | success=True, data populated |
| `test_agent_result_failure` | success=False, error_message set |
| `test_agent_result_generic_type` | `AgentResult[Analysis]` works |
| `test_create_agent_context` | Factory produces valid context |

**`tests/types/test_messages.py`** (~70 lines, 6 tests):
| Test | Validates |
|------|-----------|
| `test_message_type_classification` | is_task_message, is_data_message, is_control_message |
| `test_message_priority_ordering` | HIGH < MEDIUM < LOW |
| `test_agent_message_defaults` | uuid generated, timestamp set, priority=MEDIUM |
| `test_agent_message_generic_payload` | Typed payloads work |
| `test_create_message_factory` | Factory produces correct message |
| `test_broadcast_message_no_to_agent` | to_agent=None for broadcasts |

**`tests/types/test_backward_compat.py`** (~30 lines, 2 tests):
| Test | Validates |
|------|-----------|
| `test_models_reexport` | All 17 types importable from `nightwatch.models` |
| `test_types_reexport` | All types importable from `nightwatch.types` |

## 6. Validation Criteria

- [ ] Every type previously in `models.py` is accessible via `from nightwatch.models import X`
- [ ] Every type is also accessible via `from nightwatch.types import X`
- [ ] Every type is accessible via its specific module: `from nightwatch.types.core import Confidence`
- [ ] New enums (`PatternType`, `MatchType`) replace string literals
- [ ] Generic `AgentResult[T]` works with type checking
- [ ] All existing test files pass without modification
- [ ] `ruff check` and `ruff format --check` pass
- [ ] Zero circular imports

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Circular imports in types/ package | Low | Types depend on nothing external; strict one-way dependency |
| StrEnum change breaks pattern serialization | Low | StrEnum inherits from str — identical JSON serialization |
| Missing re-export breaks consumer | Medium | Comprehensive backward compat test covers all 17 types |

## 8. Commit Message

```
refactor(types): split models.py into domain-segmented type system

Split monolithic models.py (17 types) into nightwatch/types/ package with
8 domain modules. All existing imports work via re-export shim. New generic
types AgentResult[T], AgentMessage[T] for agent framework. StrEnum replaces
string literals for PatternType and MatchType.

GANDALF-001a
```
