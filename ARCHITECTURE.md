# Architecture

## Design Principles

- Keep the composition DSL independent from execution backend
- Keep request objects immutable and serializable
- Make extension points explicit
- Start simple and typed, then widen capabilities iteratively

## Component Map

### 1. DSL Layer (`pyflow`)

Responsible for request composition:

- `Request` + `Step` + `Context`
- `PromptStep` and `TestStep`
- Context helpers: `docs(...)`, `code(...)`
- Step helper: `tests(...)`
- Rendering via `Request.render()`

### 2. Tool Layer (planned)

Responsible for custom tool definition and normalization:

- `ToolRef` for OpenHands-compatible tool references
- `@tool` decorator producing `FunctionTool`

### 3. Runtime Model Layer

Responsible for model/provider config:

- `Model` abstract base with `build_llm()`
- `AIModel` for provider-backed LLM config
- `TestModel` for scripted offline `TestLLM` runs

### 4. Agent Layer

Responsible for executable user-facing object:

- `Agent(model=...)` stores a built OpenHands agent instance
- Agent-level contexts render as a global prompt preamble
- Supports sink execution (`request >> agent`) and returns OpenHands conversation

### 5. OpenHand SDK Integration

- Direct integration with OpenHands SDK runtime primitives (`LLM`, `Conversation`, `TestLLM`)
- No backend abstraction layer yet

## Module Dependency Graph (Runtime)

- `context.py` -> `steps.py`, `utils.py` (coercion for `@`)
- `steps.py` -> `utils.py`
- `request.py` -> `context.py`, `steps.py`, `utils.py`
- `__init__.py` -> `context.py`, `steps.py`, `request.py`

Type-check-only imports are used to avoid runtime cycles (e.g., `steps.py` references `Context` only in typing).

## Data Flow

1. User composes `Request` with `>>` and `@`
2. User executes via sink: `request >> agent` or `request >> model`
3. Agent renders prompt + global context preamble
4. OpenHands conversation runs and returns execution session data

## Planned Extensions

- Context inclusion/exclusion policies at file/class granularity
- Skill packs and reusable prompt templates
- Approval hooks and interactive command-line controls
- Parallel orchestration constraints and multi-agent task graphs
- Backend plug-ins beyond OpenHands
- Integration test marker for real `Conversation.run()` environments
