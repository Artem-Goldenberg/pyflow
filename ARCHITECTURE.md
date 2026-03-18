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

### 2. Tool Layer (`pyflow.tooling`)

Responsible for tool definition, composition, and OpenHands compilation:

- `Tool` base context for attachable tool instructions
- `FunctionTool` for both:
  - local Python functions registered via `@tool`, where the latest registration wins by name
  - wrapped OpenHands tools created via `FunctionTool.from_openhands(...)`, which eagerly imports and registers the underlying OpenHands tool
- `ToolSet` and `tools(...)` for immutable composition and lookup-driven flattening
- compile boundary via `compile_openhands_tools(...)`, which keeps the last attached tool for each name

### 3. Runtime Model Layer

Responsible for model/provider config:

- `Model` abstract base with `build_llm()`
- `AIModel` for provider-backed LLM config
- `TestModel` for scripted offline `TestLLM` runs

### 4. Agent Layer

Responsible for executable user-facing object:

- `Agent(model=...)` stores a built OpenHands agent instance
- Agent-level contexts render as a global prompt preamble
- Supports sink execution (`request >> agent`) and returns a pyflow `Session`

### 5. Session Layer (`pyflow.session`)

Responsible for resumable runtime execution handles:

- `Session` wraps a live OpenHands `Conversation`
- Supports continuation sink execution (`request >> session`)
- Exposes backend conversation access via `session.conversation`

### 6. OpenHand SDK Integration

- Direct integration with OpenHands SDK runtime primitives (`LLM`, `Conversation`, `TestLLM`)
- No backend abstraction layer yet

## Module Dependency Graph (Runtime)

- `context.py` -> `steps.py`, `utils.py` (coercion for `@`)
- `steps.py` -> `utils.py`
- `request.py` -> `context.py`, `steps.py`, `utils.py`
- `session.py` -> `request.py`, `sink.py`, `tooling.py`, `utils.py`
- `__init__.py` -> `context.py`, `steps.py`, `request.py`, `session.py`

Type-check-only imports are used to avoid runtime cycles (e.g., `steps.py` references `Context` only in typing).

## Data Flow

1. User composes `Request` with `>>` and `@`
2. User executes via sink: `request >> agent` or `request >> model`
3. Agent renders prompt + global context preamble
4. OpenHands conversation runs and returns a pyflow `Session`
5. User can continue the same runtime via `request >> session`

## Planned Extensions

- Context inclusion/exclusion policies at file/class granularity
- Skill packs and reusable prompt templates
- Approval hooks and interactive command-line controls
- Parallel orchestration constraints and multi-agent task graphs
- Backend plug-ins beyond OpenHands
- Integration test marker for real `Conversation.run()` environments
