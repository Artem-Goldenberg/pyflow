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

Responsible for owning and constructing runtime LLM wrappers:

- `Model` abstract base plus public factory surface (`from_api(...)`, `subscription(...)`, `test(...)`)
- `AIModel` wrapper around one live OpenHands `LLM`
- `TestModel` wrapper around one live `TestLLM` plus a pyflow-owned scripted-response record
- Non-public fresh-runtime cloning hook for isolated worker execution (`_fresh_runtime_model()`)

### 3.1 Generated Model Registry (`pyflow.models`)

Responsible for exposing provider-discovered models as Python attributes:

- `generate_models_from_provider(...)` calls a provider `/models` endpoint, then writes a generated `models` registry module
- The generated `models` registry nests provider namespaces directly inside `models` and also exposes a flat top-level view (`models.<provider>_<alias>`)
- Every generated model property access constructs a fresh `Model`; generated properties do not cache model instances
- `api_key` passed to generation is used only for the discovery request and is not embedded into the generated module
- Runtime model access always resolves credentials from `api_key_env_var` when the property is read

### 4. Agent Layer

Responsible for executable user-facing object:

- `Agent(model=...)` consumes `model.inner_llm` and stores a built OpenHands agent instance
- Agent-level contexts render as a global prompt preamble
- Supports sink execution (`request >> agent`) and returns a pyflow `Session`
- Supports synchronous batch execution via `Agent.parallel(...)`, returning ordered `Session | ParallelFailure` entries

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
4. Agent uses the model's owned OpenHands `LLM` to create a fresh conversation run
5. OpenHands conversation runs and returns a pyflow `Session`
6. User can continue the same runtime via `request >> session`

Parallel batch flow:

1. User calls `agent.parallel(items, build_request, max_concurrency=...)`
2. Pyflow converts each built request input into a `Request`
3. Each worker clones a fresh runtime model via `_fresh_runtime_model()`
4. Each worker creates and runs its own OpenHands conversation
5. Pyflow returns results in original input order as `Session | ParallelFailure`

## Planned Extensions

- Context inclusion/exclusion policies at file/class granularity
- Skill packs and reusable prompt templates
- Approval hooks and interactive command-line controls
- Parallel orchestration constraints and multi-agent task graphs
- Backend plug-ins beyond OpenHands
- Integration test marker for real `Conversation.run()` environments
