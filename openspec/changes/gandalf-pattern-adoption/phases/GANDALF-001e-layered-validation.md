# OpenSpec Proposal: GANDALF-001e — Layered Validation

**ID**: GANDALF-001e
**Parent**: GANDALF-001 (Gandalf Pattern Adoption)
**Status**: Proposed
**Phase**: 5 of 5
**Date**: 2026-02-05
**Scope**: Replace `validation.py:validate_file_changes()` with composable validator chain
**Dependencies**: GANDALF-001a (Type System Foundation)
**Estimated Effort**: 2-3 hours

---

## 1. Goal

Replace the single `validation.py:validate_file_changes()` function (143 lines, ad-hoc checks) with a composable validation pipeline following Gandalf's layered validator pattern. 5 stateless validators run in sequence with short-circuit on path safety failure. Two new validators (Semantic, Quality) add capabilities not present today.

## 2. Problem

Current `validation.py` (143 lines) has:
- All validation logic in one function with ad-hoc checks
- No separation between different validation concerns
- No way to add/remove/reorder validators without modifying the function
- No semantic validation (does the fix match the root cause?)
- No quality validation (confidence thresholds, file change limits)
- No structured result types — just `list[str]` for errors and warnings

## 3. What Changes

### 3.1 New Package Structure

Migrate `nightwatch/validation.py` (file) → `nightwatch/validation/` (package):

```
nightwatch/validation/
├── __init__.py              # Re-exports validate_file_changes for backward compat
├── _legacy.py               # Original validation.py content (renamed)
├── orchestrator.py          # ValidationOrchestrator — runs layers in sequence
└── layers/
    ├── __init__.py
    ├── path_safety.py       # Path traversal, absolute path checks (extracted)
    ├── content.py           # Non-empty content, suspicious length (extracted)
    ├── syntax.py            # Ruby block counting (extracted)
    ├── semantic.py          # NEW: Does fix match root cause modules?
    └── quality.py           # NEW: Confidence thresholds, file change limits
```

### 3.2 Extracted Validators (from existing validation.py)

**PathSafetyValidator** (`path_safety.py`, ~40 lines):
- Checks for absolute paths (`/etc/passwd`)
- Checks for path traversal (`../../etc`)
- **Short-circuits**: if paths are unsafe, remaining layers are skipped
- Extracted from `_validate_single_change()` lines 70-72

**ContentValidator** (`content.py`, ~40 lines):
- Checks content is non-empty for create/modify actions
- Warns on suspiciously short content (<20 chars)
- Extracted from `_validate_single_change()` lines 74-84

**SyntaxValidator** (`syntax.py`, ~50 lines):
- Ruby block balance checking (def/end, class/end, module/end)
- Extracted from `_check_ruby_syntax()` lines 107-142
- Only runs on `.rb` files

### 3.3 New Validators

**SemanticValidator** (`semantic.py`, ~60 lines):
- Checks if modified files relate to the identified root cause modules
- Warns if number of changes seems disproportionate to fix scope
- Requires analysis context to compare file changes against root cause

**QualityValidator** (`quality.py`, ~45 lines):
- Checks confidence meets minimum threshold (default: MEDIUM)
- Checks file change count doesn't exceed maximum (default: 5)
- Checks analysis has non-empty reasoning and root_cause
- Requires analysis context

### 3.4 ValidationOrchestrator (`orchestrator.py`, ~55 lines)

```python
class ValidationOrchestrator:
    def __init__(self, layers=None):
        self.layers = layers or [
            PathSafetyValidator(),
            ContentValidator(),
            SyntaxValidator(),
            SemanticValidator(),
            QualityValidator(),
        ]

    def validate(self, file_changes, context=None) -> ValidationResult:
        # Run each layer in sequence
        # Short-circuit on PATH_SAFETY failure
        # Aggregate into ValidationResult with blocking_errors + warnings
```

### 3.5 Module-to-Package Migration

1. Rename `nightwatch/validation.py` → `nightwatch/validation/_legacy.py`
2. Create `nightwatch/validation/__init__.py`:

```python
from nightwatch.validation._legacy import validate_file_changes
from nightwatch.validation.orchestrator import ValidationOrchestrator

__all__ = ["validate_file_changes", "ValidationOrchestrator"]
```

All existing `from nightwatch.validation import validate_file_changes` statements continue to work.

### 3.6 Validator Protocol

All validators implement the `IValidator` protocol (from GANDALF-001a types):

```python
class IValidator(Protocol):
    def validate(self, file_changes: list[Any], context: dict[str, Any] | None = None) -> LayerResult: ...
```

This means custom validators can be added by any consumer without modifying the orchestrator.

## 4. What Doesn't Change

- `from nightwatch.validation import validate_file_changes` continues to work
- `validate_file_changes(analysis, github_client)` produces same results
- Existing validation behavior preserved in `_legacy.py`
- `runner.py` import unchanged
- No new dependencies

## 5. Tests

**`tests/validation/test_orchestrator.py`** (~80 lines, 5 tests):
| Test | Validates |
|------|-----------|
| `test_all_layers_run_on_valid_input` | 5 LayerResults in output |
| `test_short_circuit_on_path_safety` | Only 1 LayerResult when path is absolute |
| `test_custom_layer_order` | Constructor accepts custom layer list |
| `test_blocking_errors_aggregated` | Errors from multiple layers in blocking_errors |
| `test_valid_true_when_no_errors` | All warnings → valid=True |

**`tests/validation/layers/test_path_safety.py`** (~40 lines, 3 tests):
| Test | Validates |
|------|-----------|
| `test_absolute_path_fails` | `/etc/passwd` → ERROR |
| `test_path_traversal_fails` | `../../etc` → ERROR |
| `test_relative_path_passes` | `app/models/user.rb` → pass |

**`tests/validation/layers/test_content.py`** (~40 lines, 3 tests):
| Test | Validates |
|------|-----------|
| `test_empty_content_modify_fails` | Empty content on modify → ERROR |
| `test_short_content_warns` | <20 chars on modify → WARNING |
| `test_valid_content_passes` | Normal content → pass |

**`tests/validation/layers/test_syntax.py`** (~40 lines, 3 tests):
| Test | Validates |
|------|-----------|
| `test_balanced_ruby_blocks` | Equal def/end → pass |
| `test_unbalanced_ruby_blocks` | Missing end → ERROR |
| `test_non_ruby_skipped` | `.py` file → pass (no Ruby check) |

**`tests/validation/layers/test_semantic.py`** (~40 lines, 2 tests):
| Test | Validates |
|------|-----------|
| `test_changes_match_root_cause_modules` | Modified files in root cause path → pass |
| `test_too_many_changes_warns` | >5 file changes → WARNING |

**`tests/validation/layers/test_quality.py`** (~40 lines, 2 tests):
| Test | Validates |
|------|-----------|
| `test_low_confidence_fails` | LOW confidence → ERROR |
| `test_missing_root_cause_fails` | Empty root_cause → ERROR |

## 6. Validation Criteria

- [ ] `ValidationOrchestrator` runs all 5 layers in order
- [ ] PATH_SAFETY failure short-circuits remaining layers
- [ ] `from nightwatch.validation import validate_file_changes` still works
- [ ] SemanticValidator catches unrelated file changes
- [ ] QualityValidator enforces confidence thresholds
- [ ] Custom validator lists accepted by orchestrator constructor
- [ ] All existing tests pass
- [ ] `ruff check` passes

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Module-to-package migration breaks imports | Medium | Re-export shim + test |
| SemanticValidator false positives | Medium | Conservative checks, only WARNING severity for ambiguous cases |
| QualityValidator too strict | Low | Configurable thresholds via constructor parameters |

## 8. Commit Message

```
refactor(validation): add layered validation pipeline

5 composable validators with short-circuit on path safety failure.
New SemanticValidator and QualityValidator. Adopts Gandalf's stateless
validator pattern with IValidator protocol. validation.py migrated
to validation/ package with backward compat.

GANDALF-001e
```
