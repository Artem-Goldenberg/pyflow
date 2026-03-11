# Implementation Plan

## Current Status (completed)

- `Request` core infrastructure is implemented
- `Agent/Model` initial implementation is implemented

## Phase 2: Tool Abstraction Layer

- Implement a Pythonic tool interface to avoid OpenHands boilerplate
- Support function-based tools (`@tool`) and class-based tools behind a unified abstraction
- Allow tools to be attached to both `Request` and `Agent`
- Add adapter translation from pyflow tools to OpenHands tool registration
- Investigate MCP-backed tool integration and reuse OpenHands MCP support where possible

## Phase 3: Execution UX (terminal-first)

- Build Python REPL-friendly execution flow for running requests on agents
- Add live run visibility around session events and progress
- Introduce approval UX for tool actions once tool support lands
- Keep behavior compatible with OpenHands conversation/event model

## Phase 4: Notebook UX

- Add notebook-first execution path for Jupyter
- Provide notebook UI for progress/interaction (streaming + approvals), potentially via `ipywidgets`
- Ensure parity of core execution semantics between REPL and notebook modes

## Phase 5: IDE Autocomplete Helpers

- Add context/code generation helpers for file-system-aware prompt inputs
- Enable patterns like generated typed module access (`code.folder.file`) for autocomplete
- Extend the same generation pattern to other utility surfaces where it improves ergonomics
- Later, consider model-endpoint-aware typed helpers once endpoint discovery is stable

## Phase 6: Advanced DSL Capabilities (later, on stable foundation)

- Extend request language with sub-agent creation/composition
- Add parallel request execution semantics
- Keep syntax concise and naturally aligned with existing `@` and `>>` operators
- Gate this phase on a mature, tested core system

## Cross-Cutting Quality Gates

- Maintain strict typing (`.venv/bin/pyright`) and operator-behavior test coverage
- Add regression tests for `@` vs `>>` precedence as DSL expands
- Expand examples alongside each new capability to validate ergonomics
