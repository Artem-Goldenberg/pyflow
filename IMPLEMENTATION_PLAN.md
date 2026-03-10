# Implementation Plan

## Phase 0: Bootstrap (completed)

- Initialize repository and Python package metadata
- Create virtual environment and dependencies
- Set up pytest baseline
- Add initial typed DSL + backend adapter skeleton
- Add usage examples and core docs

## Phase 1: DSL Ergonomics

- Add more request examples mirroring real workflows
- Refine operator semantics for `>>` and `@`
- Add richer attachment primitives (skills, context scopes, exclusions)
- Add serialization for requests (JSON/YAML)

## Phase 2: OpenHands Integration Hardening

- Improve request-to-agent compilation rules
- Map pyflow constraints to OpenHands hooks/policies
- Add execution options (timeouts, retries, max iterations)
- Add session replay helpers from `SessionLog`

## Phase 3: Interactive Runtime

- Add TUI/REPL execution shell for live progress
- Implement tool-approval prompts and overrides
- Add notebook-friendly streaming output adapter

## Phase 4: Extensibility

- Stabilize plugin API for custom tools/skills/context providers
- Add pattern libraries (reusable request templates)
- Support user-defined post-run automations (tests/commit/MR)

## Phase 5: Multi-Agent Orchestration

- Add parallelization constraints and scheduling strategies
- Add parent/child request graph execution
- Add shared context and conflict resolution policy

## Cross-Cutting Quality Gates

- Strong typing and static checks
- Unit tests around DSL semantics and adapters
- Integration smoke tests (with mocked OpenHands or test models)
- Versioned public API docs
