# NightWatch Feature Specifications

## Implemented Features

### COMPOUND-001: Compound Intelligence System

**[Implementation Plan](./COMPOUND-001-implementation-plan.md)**
- **Status**: Completed
- **Completion**: 100%
- **Scope**: Synthesized implementation of 3 openspec proposals (compound-engineering-patterns, ralph-integration, compound-product-integration)

| Phase | Name | Status |
|-------|------|--------|
| 1 | Knowledge Foundation | Completed |
| 2 | Analysis Enhancement | Completed |
| 3 | Quality Gates & Run Context | Completed |
| 4 | Compound Intelligence | Completed |
| 5 | Self-Health Report | Completed |

### MAINT-001: Maintenance Workflows

- **Status**: Completed
- **Scope**: Workflow architecture, CI Doctor, pattern analysis, guardrails generation
- **PR**: #4 (feat/all-specs -> main)

### GANDALF-001: Pipeline Orchestrator

- **Status**: Completed
- **Scope**: Phase-based execution pipeline with type system, base agent registry, message bus, state management

### OPIK-001: Observability Integration

- **Status**: Completed
- **Scope**: Opik observability for Claude API calls

### TOOL-002: AGENTS.md Evaluation

- **Status**: Completed
- **Scope**: Agent definition files for specialized analysis modes

### TEST-001: Comprehensive Test Suite

- **Status**: Completed
- **Completion**: 648 tests, 86.40% coverage (threshold: 85%)
- **Scope**: Unit tests, integration tests, shared fixtures and factories

### Context Efficiency

- **Status**: Completed
- **Scope**: Token optimization across multiple layers
- **Phases Implemented**:
  - Phase 1: Token budgeting, adaptive iterations, adaptive thinking
  - Phase 2: Anthropic beta context editing (clear_thinking + clear_tool_uses)
  - Phase 3: Cross-error context sharing, code cache
  - Phase 4.1: Message Batching API (nightwatch/batch.py)
  - Phase 4.3: Tool result truncation

## Planned Features

### PLUGIN-001: Claude Code Plugin Adoption

**[Implementation Plan](./PLUGIN-001-implementation-plan.md)**
- **Status**: Ready to Execute (external plugin installation, not NightWatch code)
- **Completion**: 0%
- **Next**: Phase 0 — install pyright binary, then Phase 1 — add demo marketplace
- **Scope**: 8 plugins across 2 tiers (pyright-lsp, security-guidance, github, commit-commands, pr-review-toolkit, slack, sentry, code-review)

## Openspec Proposals

| ID | Proposal | PR | Status |
|----|----------|-----|--------|
| COMPOUND-001a | [compound-engineering-patterns](../../openspec/changes/compound-engineering-patterns/proposal.md) | [#1](../../pull/1) | Completed |
| RALPH-001 | [ralph-integration](../../openspec/changes/ralph-integration/proposal.md) | [#2](../../pull/2) | Completed |
| COMPOUND-001b | [compound-product-integration](../../openspec/compound-product-integration/proposal.md) | [#3](../../pull/3) | Completed |
| PLUGIN-001 | [Claude Code Plugin Adoption Strategy](../../.claude/OPENSPEC-claude-code-plugins.md) | — | Draft |
| IMPL-001 | [unified-implementation-plan](../../openspec/changes/unified-implementation-plan/implementation.md) | — | Completed |
| MAINT-001 | [maintenance-workflows](../../openspec/changes/maintenance-workflows/proposal.md) | #4 | Completed |
| OPIK-001 | [opik-observability](../../openspec/changes/opik-observability/implementation.md) | — | Completed |
| TOOL-002 | [agents-md-evaluation](../../openspec/changes/agents-md-evaluation/implementation-plan.md) | — | Completed |
| GANDALF-001 | [gandalf-pattern-adoption](../../openspec/changes/gandalf-pattern-adoption/proposal.md) | — | Completed |
| CTX-001 | [context-efficiency](../../openspec/context-efficiency/proposal.md) | — | Completed |
| TEST-001 | [comprehensive-test-suite](../../openspec/testing/comprehensive-test-suite/implementation-plan.md) | — | Completed |
