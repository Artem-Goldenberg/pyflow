# AGENTS.md

## Project Goal

Build a high-level Python framework for composing and executing agent requests programmatically.

The framework should support:

- Declarative request composition (prompt, tools, context, docs, skills, constraints)
- Reusable patterns and extension points
- A Pythonic custom tool interface (`@tool` decorator + class-based tools)
- Execution through OpenHands SDK adapters
- Session visibility and eventually interactive intervention during execution
- Post-run actions (tests, commit, MR/PR automation)

## Current Backend Decision

Primary backend is **OpenHands SDK** (`openhands-sdk` + `openhands-tools`).

Design rule: `pyflow` remains backend-agnostic at the DSL layer, with adapters for runtime execution.

## Core Abstractions (Bootstrap)

- `Request`: immutable composition unit (`>>` for sequencing, `@` for attachments)
- `Agent`: executable runtime wrapper around `Model` + backend
- `Model`: provider/model configuration and discovery helpers
- `ToolRef` / `FunctionTool`: explicit tool references and function-based custom tools
- `ExecutionBackend`: abstract backend interface; `OpenHandsBackend` as first implementation
- `SessionLog`: normalized execution result payload

## Conventions

- Always use type annotations
- Use `TypeVar`/`ParamSpec`/protocols where they improve API safety
- Prefer dataclasses and abstract base classes when appropriate
- Keep modules flat and focused
- Keep APIs immutable by default for request composition

## Import Style

Sort imports in this order:

1. `import ...`
2. `from ... import ...`

## Testing

- Use `pytest`
- Cover DSL operator behavior, typing-sensitive logic, and backend compilation boundaries
- Add regression tests for operator precedence edge cases (`@` vs `>>`)

## Near-Term Priorities

1. Expand DSL examples and validate ergonomics
2. Define interactive terminal/repl output strategy and approval UX
3. Stabilize abstraction boundaries (`Request`, `Agent`, `Model`, tool system)
4. Deepen OpenHands adapter coverage (skills, context windows, tool approvals, hooks)
5. Add notebook-first execution flow support
