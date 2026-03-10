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

### 3. Runtime Model Layer (planned)

Responsible for model/provider config:

- `Model` for runtime LLM settings
- `ModelCatalog` for endpoint-based model discovery

### 4. Agent Layer (planned)

Responsible for executable user-facing object:

- Binds `Model` + `ExecutionBackend`
- Applies default request attachments
- Executes request and returns `SessionLog`

### 5. OpenHand SDK Integration (planned)

## Module Dependency Graph (Runtime)

- `context.py` -> `steps.py`, `utils.py` (coercion for `@`)
- `steps.py` -> `utils.py`
- `request.py` -> `context.py`, `steps.py`, `utils.py`
- `__init__.py` -> `context.py`, `steps.py`, `request.py`

Type-check-only imports are used to avoid runtime cycles (e.g., `steps.py` references `Context` only in typing).

## Data Flow

1. User composes `Request` with `>>` and `@`
2. User renders a human-readable prompt via `Request.render()`
3. Execution backends and agent runtimes are planned extensions

## Planned Extensions

- Context inclusion/exclusion policies at file/class granularity
- Skill packs and reusable prompt templates
- Approval hooks and interactive command-line controls
- Parallel orchestration constraints and multi-agent task graphs
- Backend plug-ins beyond OpenHands
