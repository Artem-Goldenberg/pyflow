# Make Pyflow Models Own Live OpenHands `LLM` Instances

## Summary

Pyflow already has a working runtime model layer, but its current design treats `Model` objects as immutable configuration that builds a fresh OpenHands `LLM` when a new run starts. That design prevents a single pyflow model object from naturally owning one long-lived `LLM` instance whose metrics, telemetry, and runtime identity accumulate across multiple independent runs.

This task changes the model architecture so pyflow models directly own live OpenHands `LLM` instances. `Model` becomes the main public factory surface for creating API-backed, subscription-backed, and test-backed models, while `AIModel` and `TestModel` become thin typed wrappers around already-constructed `LLM` and `TestLLM` objects. `TestModel` must also keep a pyflow-owned copy of its scripted responses so users can inspect them directly without depending on OpenHands internals. After implementation, testing must confirm the new factory surface, shared-per-model `LLM` reuse across runs, subscription construction behavior, correct `TestLLM` wrapping semantics, scripted-response retrieval, and compatibility with the existing `Agent` and `Session` execution flow.

## Introduction

### Prerequisites

- **Documentation**
  - `AGENTS.md`
    - `Core Abstractions`
    - `Conventions`
    - `Testing`
    This document matters because it defines the project’s current abstractions, type-safety expectations, and the rule that ambiguous API choices should be made explicit.
  - `ARCHITECTURE.md`
    - `Component Map`, especially `Runtime Model Layer`
    - `Data Flow`
    This document matters because it currently describes `Model` as the object that builds OpenHands `LLM` instances for execution, which is exactly the architecture this task will change.
  - `README.md`
    - `Status`
    - `Minimal pyflow Example`
    - `Offline Runtime Tests`
    This document matters because it currently documents `AIModel` as a provider-configuration object and `TestModel` as a scripted offline model.
  - Installed OpenHands SDK API
    - `openhands.sdk.LLM`
    - `openhands.sdk.LLM.subscription_login(...)`
    - `openhands.sdk.LLM.is_subscription`
    - `openhands.sdk.testing.TestLLM`
    This API matters because pyflow will wrap live OpenHands `LLM` objects directly instead of storing only constructor inputs.
  - `IMPLEMENTATION_PLAN.md`
    - `Current Status`
    - `Cross-Cutting Quality Gates`
    This file matters because it confirms that the `Agent/Model` layer is still in bootstrap and that type checking and runtime regression coverage remain required.

- **Related code**
  - `pyflow/model.py` — current `Model`, `AIModel`, and `TestModel` definitions based on `build_llm()`
  - `pyflow/agent.py` — current runtime path that asks the model to build an `LLM` for each fresh run
  - `pyflow/__init__.py` — current public export surface for model types
  - `tests/test_runtime.py` — existing runtime-model behavior coverage, especially expectations around `build_llm()` and `TestModel`
  - `.venv/lib/python3.12/site-packages/openhands/sdk/llm/llm.py` — OpenHands `LLM` runtime state and side effects
  - `.venv/lib/python3.12/site-packages/openhands/sdk/testing/test_llm.py` — OpenHands `TestLLM` scripted-response behavior and visible inspection surface

### Problem

Currently, pyflow already has a coherent execution flow: `Model.__rrshift__` delegates through `Agent`, `Agent` creates a fresh OpenHands `Conversation` for each new run, and `Session` continuation keeps using the same live conversation after the first run.

But the model abstraction is currently centered around delayed `LLM` construction rather than `LLM` ownership. In [pyflow/model.py](/Users/goldenberg/Developer/pyflow/pyflow/model.py), `AIModel` stores provider fields such as `name`, `api_key`, and `base_url`, while `TestModel` stores scripted responses rather than a `TestLLM`. In [pyflow/agent.py](/Users/goldenberg/Developer/pyflow/pyflow/agent.py), every fresh run asks the model to build a new OpenHands `LLM`. This means the pyflow model instance is not the actual runtime identity of the LLM, and metrics, telemetry, and other instance-owned state belong to whichever OpenHands `LLM` happened to be created for a particular run rather than to the pyflow model object itself.

That mismatch is especially visible for the requested subscription flow and for user expectations around metrics. If a pyflow model is supposed to represent “the model I am using,” then it is reasonable for that object to own one live OpenHands `LLM` whose usage accumulates across all runs launched through that model. The current design works against that because `Model` is only a recipe, not the runtime object. It also leaves no natural public place for `Model.subscription(...)` to return a model that already embodies the authenticated OpenHands `LLM`.

This task solves the problem by changing the runtime model layer from “config that can build an LLM” to “wrapper that owns an LLM.” The new design treats the pyflow model object as the stable identity that carries one live OpenHands `LLM` instance across runs, so model-level metrics and subscription-backed authentication are properties of the model itself rather than of freshly created backend objects.

### Task

This task belongs to the runtime model layer and intentionally changes its architecture. Pyflow models must stop being only `LLM` factories and instead become thin typed wrappers around already-created OpenHands `LLM` objects. The new public API should be centered on `Model` as the main entry point for constructing these wrappers.

The required behavior is:

- pyflow `Model` objects must own a live OpenHands `LLM` instance directly rather than create one later via `build_llm()`
- `Agent` must consume the model’s owned `LLM` instead of asking the model to build a fresh one for each new run
- independent runs started with the same pyflow model instance must reuse the same underlying OpenHands `LLM`
- model-level OpenHands metrics and telemetry must therefore accumulate on that shared `LLM` instance across multiple runs started from the same model
- `Model` must become the main public factory surface for real-provider, subscription-backed, and test-backed model creation
- `AIModel` must become the concrete wrapper for a live OpenHands `LLM`
- `TestModel` must become the concrete wrapper for a live OpenHands `TestLLM`

The preferred public factory shape is:

- `Model(...)` for API-backed `LLM` creation, returning an `AIModel`
- `Model.subscription(...)` for subscription-backed `LLM` creation, returning an `AIModel`
- `Model.test(...)` for test-backed `TestLLM` creation, returning a `TestModel`

The approved fallback, only if the primary `Model(...)` form cannot be typed or justified cleanly, is:

- `Model.from_api(...)` instead of `Model(...)`

The scope of this task is exactly the following:

- redesign `Model` so it owns or exposes a live `LLM`
- remove `build_llm()` as the central runtime contract
- update `AIModel` and `TestModel` so their constructors accept already-created OpenHands `LLM` objects
- make `TestModel` store its scripted responses separately from the wrapped `TestLLM`
- add the `Model`-level factory surface for API, subscription, and test construction
- make shared-`LLM` reuse across multiple runs an intentional public behavior
- document the new semantics, especially the fact that repeated runs through one model share one `LLM` instance

The scope explicitly excludes:

- changing request composition syntax or the `>>` DSL itself
- changing `Session` continuation semantics within an already-running conversation
- changing tool execution, request rendering, or notebook/repl UX
- inventing pyflow-owned credential storage or authentication mechanisms beyond what OpenHands already provides
- guaranteeing isolation between separate runs launched from the same model instance; the new architecture intentionally shares one `LLM` per pyflow model

The completion of this task must produce the following user-facing changes.

#### 1. `Model` becomes the main public factory surface

Current public usage constructs `AIModel` directly from provider configuration:

```python
from pydantic import SecretStr
from pyflow import AIModel

model = AIModel(
    name="openai/gpt-4.1",
    api_key=SecretStr("..."),
    base_url="https://api.openai.com/v1",
)
```

After this task, the main user-facing construction path must move to `Model`.

Preferred illustrative example:

```python
from pydantic import SecretStr
from pyflow import AIModel, Model

model = Model(
    name="openai/gpt-4.1",
    api_key=SecretStr("..."),
    base_url="https://api.openai.com/v1",
)

assert isinstance(model, AIModel)
```

Approved fallback example if the preferred form proves untenable:

```python
from pydantic import SecretStr
from pyflow import AIModel, Model

model = Model.from_api(
    name="openai/gpt-4.1",
    api_key=SecretStr("..."),
    base_url="https://api.openai.com/v1",
)

assert isinstance(model, AIModel)
```

Expected behavior:

- the public story is “construct models from `Model`,” not “instantiate separate subclasses directly for ordinary use”
- the resulting object is an `AIModel`
- the `AIModel` already owns a live OpenHands `LLM`
- users may still directly wrap a prebuilt `LLM` by constructing `AIModel(llm=...)` when they need explicit control

#### 2. Subscription-backed construction happens through `Model.subscription(...)`

This task introduces the following new public API names:

- `Model.subscription`
- `Model.test`

The subscription path must create the OpenHands `LLM` up front and wrap it immediately. `Model.test(...)` must create and return a `TestModel`, not a generic `Model` or `AIModel`.

Illustrative example:

```python
from pyflow import AIModel, Model

model = Model.subscription(
    vendor="openai",
    model="gpt-5.2-codex",
    force_login=False,
    open_browser=True,
)

assert isinstance(model, AIModel)
assert model.llm.is_subscription is True
```

Expected behavior:

- `Model.subscription(...)` constructs the OpenHands subscription-backed `LLM` through `LLM.subscription_login(...)`
- the returned object is an `AIModel` that wraps that live `LLM`
- because the model now owns the live `LLM`, authentication and login-related OpenHands side effects happen when the pyflow model is constructed, not later during `request >> model`
- unsupported vendor/model combinations fail during model construction rather than during a later `build_llm()` call

#### 3. `AIModel` and `TestModel` wrap live LLM objects directly

Current `AIModel` and `TestModel` store constructor inputs and then create an `LLM` later. After this task, the concrete model wrappers must hold the already-created OpenHands objects. `TestModel` must additionally preserve a pyflow-owned record of the scripted responses used to seed its wrapped `TestLLM`.

Illustrative examples:

```python
from openhands.sdk import LLM
from openhands.sdk.testing import TestLLM
from pyflow import AIModel, TestModel

ai_model = AIModel(
    llm=LLM(
        model="openai/gpt-4.1",
        api_key="...",
    )
)

test_model = TestModel(
    llm=TestLLM.from_messages([...]),
    scripted_responses=(...),
)
```

Expected behavior:

- `AIModel` is a typed wrapper around a live OpenHands `LLM`
- `TestModel` is a typed wrapper around a live OpenHands `TestLLM`
- `TestModel` stores `scripted_responses` as pyflow-owned data in addition to the wrapped `TestLLM`
- users can retrieve the configured scripted responses from the `TestModel` directly
- both wrappers expose the owned `llm` as stable runtime state
- pyflow no longer treats those classes as delayed-construction config containers

#### 4. Reusing one model across independent runs reuses one `LLM` and accumulates one metrics stream

This is the central semantic change of the task.

Illustrative example:

```python
from pydantic import SecretStr
from pyflow import Model

model = Model(
    name="openai/gpt-4.1",
    api_key=SecretStr("..."),
)

first = "Inspect the issue." >> model
second = "Now implement the fix." >> model

total_cost = model.llm.metrics.accumulated_cost
```

Expected behavior:

- the first and second runs create separate conversations, as they do today
- both runs use the same underlying OpenHands `LLM` instance because they share the same pyflow model object
- metrics, telemetry, and other instance-owned `LLM` state accumulate on that one shared instance
- users who want isolated metrics or isolated `LLM` state must create a fresh pyflow model object rather than reuse the old one

#### 5. `Model.test(...)` returns `TestModel` and preserves scripted responses for inspection

The test model path must follow the same “the model owns one live LLM” rule rather than preserving the old “fresh `TestLLM` per run” behavior. At the same time, `TestModel` must keep the configured scripted responses as separate pyflow-owned state so the user can inspect them even after the wrapped `TestLLM` has consumed part of its internal queue.

Illustrative example:

```python
from openhands.sdk.llm import Message, TextContent
from pyflow import Model, TestModel

model = Model.test(
    scripted_responses=(
        Message(role="assistant", content=[TextContent(text="First")]),
        Message(role="assistant", content=[TextContent(text="Second")]),
    )
)

assert isinstance(model, TestModel)
assert len(model.scripted_responses) == 2

_ = "Run one." >> model
_ = "Run two." >> model
```

Expected behavior:

- `Model.test(...)` creates one live `TestLLM` and wraps it in one `TestModel`
- `Model.test(...)` returns `TestModel`
- `TestModel.scripted_responses` preserves the original configured scripted responses for user inspection
- repeated independent runs using that same `TestModel` consume the same underlying scripted-response queue
- if a user wants a fresh script for another run, they must create a fresh `TestModel`
- this is an intentional consequence of making model identity equal to owned `LLM` identity

#### 6. Wrapping an existing `TestLLM` may accept an explicit scripted-response record, but pyflow must not rely on OpenHands private state

The user-facing API should support wrapping a prebuilt OpenHands `TestLLM`, not only constructing one from pyflow inputs.

Illustrative example:

```python
from openhands.sdk.testing import TestLLM
from pyflow import TestModel

llm = TestLLM.from_messages([...])
model = TestModel(
    llm=llm,
    scripted_responses=(...),
)
```

Expected behavior:

- the wrapped `TestModel` uses the exact provided `TestLLM` instance
- any explicit `scripted_responses` record passed to `TestModel` is stored separately for user inspection
- pyflow must not depend on the private `_scripted_responses` queue inside `TestLLM` to reconstruct the public scripted-response record

#### Notes

- New public API names introduced by this task:
  - `Model.subscription`
  - `Model.test`
- New public API name that may be introduced only if needed:
  - `Model.from_api`
- Existing public API names whose meaning changes:
  - `Model` becomes the main model-construction surface instead of being only an abstract builder contract
  - `AIModel` becomes a wrapper around a live `LLM`, not a provider-config dataclass
  - `TestModel` becomes a wrapper around a live `TestLLM` plus a pyflow-owned `scripted_responses` record
- This design intentionally changes side-effect timing. Under the new architecture, constructing a model may immediately construct a real OpenHands `LLM`; for subscription-backed models, that means authentication work may happen during `Model.subscription(...)`.
- This design intentionally changes test-model reuse semantics. The old architecture created a fresh `TestLLM` for each fresh run. The new architecture reuses one `TestLLM` per `TestModel`, so scripted responses are shared across runs.
- Because OpenHands `TestLLM` does not publicly expose the original scripted-response sequence, pyflow must keep its own public `scripted_responses` record rather than trying to reconstruct it from OpenHands internals.

### Review notes

1. Reframed the task around your requested architecture change: the model owns a live `LLM`, so metrics accumulate per model instance rather than per fresh run.
2. Removed the earlier assumption that subscription support required a separate `SubscriptionModel`; in this design, subscription-backed models are ordinary `AIModel` wrappers around subscription-authenticated OpenHands `LLM` instances.
3. Made the side-effect timing change explicit: `Model.subscription(...)` now performs OpenHands subscription construction at model-creation time, not lazily at run time.
4. Added explicit behavior for `TestModel` reuse across runs, because this is the largest semantic regression risk compared with the current fresh-`TestLLM` design.
5. Replaced the earlier private-attribute assumption for `TestLLM` with the stronger requirement that `TestModel` keeps its own public `scripted_responses` record for user inspection.

## Implementation

The implementation should be split into five goals.

### Goal 1. Refactor `pyflow.model` from an `LLM` builder contract into owned-`LLM` wrappers and factories

This goal performs the core architecture change in one place before the runtime and tests are updated around it.

#### File: `pyflow/model.py`

- Remove `Model`’s current role as an `ABC` with `build_llm()`.
- Stop using `build_llm()` as the runtime contract. The final public model API should not tell users that a pyflow model “builds” an `LLM`; it should tell them that a pyflow model “owns” one.
- Keep `Model` abstract as the shared runtime base class, even after the refactor.
- Keep `Model` abstract in the actual Python type system, not only in documentation.
- Declare the `llm` contract as an actual abstract property, not as a bare attribute annotation. Use the modern pattern:

```python
class Model(ABC):
    @property
    @abstractmethod
    def llm(self) -> LLM:
        ...
```

- Do not rely on `llm: LLM` alone to express abstractness; that is only a type annotation, not an abstract contract.
- Convert `Model` into an abstract owned-`LLM` base class that:
  - exposes `llm` through that abstract property as the stable runtime object used by `Agent`
  - keeps `__rrshift__(...)` unchanged so `request >> model` still delegates through `Agent`
  - provides the public factory entry points for API-backed, subscription-backed, and test-backed construction

- Reshape the concrete wrappers:
  - `AIModel` becomes a frozen dataclass wrapper with one required field: `llm: LLM`
  - `TestModel` becomes a frozen dataclass wrapper with required fields:
    - `llm: TestLLM`
    - `scripted_responses: Sequence[Message | Exception]`

- Keep `TestModel.scripted_responses` as the original configured script, not the remaining queue. Store it as an immutable tuple internally even if the public annotation stays `Sequence[...]`.
- Require direct `TestModel(...)` construction to receive `scripted_responses`. Do not make this field optional on the direct wrapper, because the public scripted-response record must stay trustworthy.

- Preserve current API-backed `LLM` defaults when constructing a real OpenHands `LLM`:
  - map current `AIModel(...)` inputs to `LLM(model=..., api_key=..., base_url=..., max_input_tokens=..., max_output_tokens=...)`
  - continue passing:
    - `log_completions=True`
    - `log_completions_folder="logs/completions"`

- Implement one private helper for API-backed `LLM` construction so the logic is not duplicated between the preferred and fallback public entry points:

```python
def _create_api_llm(
    *,
    name: str,
    api_key: SecretStr,
    base_url: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
) -> LLM:
    ...
```

- Implement the preferred public constructor path first:
  - add `Model.__new__(...)` so `Model(...)` returns `AIModel(llm=_create_api_llm(...))` when `cls is Model`
  - keep subclass construction working normally by delegating to `super().__new__(cls)` when `cls` is not `Model`
  - do not override `AIModel.__new__`, `TestModel.__new__`, or any other subclass `__new__` method; the direct-wrapper classes should keep normal dataclass construction
  - add overloads for `Model.__new__(...)` so the type checker sees the intended public return type
  - expose the same public API kwargs currently used for API-backed real models and pass them through to `_create_api_llm(...)`:

```python
def __new__(
    cls,
    *,
    name: str,
    api_key: SecretStr,
    base_url: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
) -> Model:
    ...
```

- Immediately validate the preferred `Model(...)` path with `.venv/bin/pyright`.
- If `Model.__new__(...)` cannot be typed cleanly without `# type: ignore`, misleading return annotations, or other type-system lies, remove that public constructor path and switch to the approved fallback:
  - `Model.from_api(...) -> AIModel`
  - keep `Model.subscription(...)` and `Model.test(...)` unchanged
  - update the rest of the implementation and tests to cover only the chosen public API, not both

- Implement `Model.subscription(...)` in the same file:
  - make it a `@staticmethod`, not a `@classmethod`, because it does not need `cls` and should always return a concrete `AIModel`
  - wrap `LLM.subscription_login(...)`
  - return `AIModel(llm=...)`
  - preserve current logging defaults by passing `log_completions=True` and `log_completions_folder="logs/completions"` through the subscription path as well
  - keep the public signature narrow and typed; do not widen this task into “accept every possible OpenHands `LLM` keyword”

- Implement `Model.test(...)` in the same file:
  - make it a `@staticmethod`, not a `@classmethod`, because it does not need `cls` and should always return a concrete `TestModel`
  - convert incoming scripted responses to a tuple once
  - build `TestLLM.from_messages(list(scripted_responses), model=name, ...)`
  - return `TestModel(llm=test_llm, scripted_responses=scripted_responses_tuple)`

- Update all docstrings in `pyflow/model.py` to describe owned `LLM` state instead of delayed construction.

#### File: `pyflow/model.py` public shape sketch

The target shape should be conceptually close to:

```python
class Model(ABC):
    @property
    @abstractmethod
    def llm(self) -> LLM:
        ...

    def __rrshift__(self, lhs: RequestInput) -> Session:
        ...

    @staticmethod
    def subscription(...) -> AIModel:
        ...

    @staticmethod
    def test(...) -> TestModel:
        ...


@dataclass(frozen=True, kw_only=True)
class AIModel(Model):
    llm: LLM


@dataclass(frozen=True, kw_only=True)
class TestModel(Model):
    llm: TestLLM
    scripted_responses: Sequence[Message | Exception]
```

If the preferred constructor survives typing cleanly:

```python
model = Model(name="openai/gpt-4.1", api_key=SecretStr("..."))
```

If it does not:

```python
model = Model.from_api(name="openai/gpt-4.1", api_key=SecretStr("..."))
```

### Goal 2. Switch the runtime to consume the owned `LLM` directly

This goal applies the architecture change to the runtime path without changing request or session semantics.

#### File: `pyflow/agent.py`

- Update `Agent` docstrings so `model` is described as owning the OpenHands `LLM`, not building one.
- Change `_build_openhands_agent()` to pass `self.model.llm` directly:

```python
return OpenHandsAgent(
    llm=self.model.llm,
    tools=list(tool_specs),
    system_prompt_kwargs={"cli_mode": True},
)
```

- Do not clone the `LLM`.
- Do not call `model_copy()`, `reset_metrics()`, or any other reset hook in this path; the whole point of the refactor is that repeated runs through one model share one backend `LLM` identity and one metrics stream.
- Keep everything else in `Agent.run(...)`, `append_message(...)`, and session continuation unchanged.

### Goal 3. Update public exports and documentation to match the new model semantics

This goal makes the architecture change legible to users and future implementers.

#### File: `pyflow/__init__.py`

- Keep exporting `Model`, `AIModel`, and `TestModel`.
- If the fallback path is required, no extra export work is needed because `Model.from_api(...)` is a static constructor on an already-exported symbol.
- No new concrete model types should be exported for this task.

#### File: `pyflow/models.py`

- No changes are needed in this file for this task.
- Do not spend implementation effort on it; the model-layer public API is defined in `pyflow/model.py` and exported through `pyflow/__init__.py`.

#### File: `README.md`

- Rewrite the minimal real-provider example to use the chosen public construction path:
  - preferred: `Model(...)`
  - fallback: `Model.from_api(...)`
- Rewrite the offline test example to use `Model.test(...)` rather than `TestModel(scripted_responses=...)`.
- Update prose around the runtime layer so it no longer says `Model` is an abstract builder.
- Add one short note explaining the new semantics:
  - one pyflow model owns one live OpenHands `LLM`
  - repeated runs through the same model share metrics and other instance-owned `LLM` state
- Add one short note on subscription models:
  - `Model.subscription(...)` may perform OpenHands authentication work during model creation

#### File: `ARCHITECTURE.md`

- Rewrite `Runtime Model Layer` from:
  - “`Model` abstract base with `build_llm()`”
  - “`AIModel` for provider-backed LLM config”
  - “`TestModel` for scripted offline `TestLLM` runs”
- To the new architecture:
  - `Model` as the public factory/wrapper entry point
  - `AIModel` as a wrapper around a live OpenHands `LLM`
  - `TestModel` as a wrapper around a live `TestLLM` plus a pyflow-owned scripted-response record
- Update the `Agent Layer` text so `Agent(model=...)` consumes `model.llm` rather than asking the model to build one.
- Update any data-flow wording that still implies “new run => model builds new LLM”.

### Goal 4. Rewrite runtime-model tests around identity sharing instead of `build_llm()`

This goal replaces the old test contract with the new one.

#### File: `tests/test_runtime.py`

- Remove tests whose whole contract is now obsolete:
  - `test_ai_model_build_llm_maps_fields`
  - `test_test_model_build_llm_uses_scripted_responses`
  - `test_session_continuation_does_not_build_fresh_llm`
  - the helper `CountingModel`

- Replace them with tests for the new public behavior.

- Cover API-backed model creation:
  - if the preferred path survives typing, add a test that `Model(...)` returns `AIModel`
  - if the fallback path is used, add the corresponding `Model.from_api(...)` test instead
  - assert that the wrapped `llm` maps the current public fields correctly (`model`, `base_url`, `api_key`, token limits)

- Cover direct wrapper construction:
  - `AIModel(llm=existing_llm)` preserves the exact `LLM` instance
  - `TestModel(llm=existing_test_llm, scripted_responses=scripted)` preserves both:
    - the exact `TestLLM` instance
    - the public `scripted_responses` record

- Cover `Model.subscription(...)` without performing real authentication:
  - monkeypatch `pyflow.model.LLM.subscription_login`
  - return a prebuilt sentinel `LLM`
  - assert that `Model.subscription(...)` returns `AIModel` wrapping that exact object
  - assert that the subscription helper is called during model creation, not delayed until execution

- Cover `Model.test(...)`:
  - assert that it returns `TestModel`
  - assert that `model.scripted_responses` equals the original configured tuple
  - assert that `model.llm` is a `TestLLM`
  - assert that using `model.llm.completion(...)` consumes the wrapped queue while `model.scripted_responses` remains unchanged

- Cover the new shared-identity runtime behavior:
  - `Agent._build_openhands_agent()` should use `model.llm` directly
  - building two fresh OpenHands agents from the same pyflow model should yield agents whose `.llm is model.llm`
  - two independent `request >> model` executions should therefore still be tied to the same owned `model.llm`

- Keep the existing continuation tests for `Session`, but update their rationale:
  - continuation should still reuse the same conversation
  - there is no longer any `build_llm()` counter to inspect

- Update helper constructors such as `_test_model_with_finishes(...)` to use `Model.test(...)` so the rest of the file follows the public API.

### Goal 5. Update all other tests and helpers that still use the old builder-style `TestModel` API

This goal keeps the rest of the test suite aligned while leaving direct-wrapper coverage concentrated in `tests/test_runtime.py`.

#### File: `tests/test_tools.py`

- Replace direct `TestModel(scripted_responses=...)` construction with `Model.test(scripted_responses=...)` in helper paths and runtime setup.
- Update `_empty_test_model()` and any other local helpers so the test file does not repeat the new construction boilerplate.
- Keep tool-runtime assertions unchanged; only the model-construction surface should move.

#### File: `tests/test_notebook_visualizer.py`

- Replace direct `TestModel(scripted_responses=...)` creation with `Model.test(...)`.
- Update `_test_model_with_finishes(...)` accordingly.
- Keep notebook visualizer assertions unchanged.

#### File: `tests/test_runtime_logging.py`

- Replace the direct `TestModel(scripted_responses=(), name="unused")` setup with `Model.test(scripted_responses=(), name="unused")`.
- Keep the logging-policy assertions unchanged.

#### File: any remaining tests found by `rg`

- Run a repository-wide search for `build_llm`, `AIModel(`, and `TestModel(` after the core refactor.
- Update any remaining test or helper that still depends on the old builder-style API.
- Leave direct `AIModel(llm=...)` or `TestModel(llm=..., scripted_responses=...)` usage only where the test is explicitly about the direct wrapper constructors.

### Review notes

1. **Pass 1:** Centered the implementation on `pyflow/model.py` first so the architecture change happens in one place before the runtime and tests are adjusted around it.
2. **Pass 2:** Kept `Model` abstract while still allowing the preferred `Model(...)` factory attempt through `Model.__new__`, and made the `Model(...)` versus `Model.from_api(...)` decision rule explicit: try `__new__` first, but fall back immediately if pyright cannot express it honestly.
3. **Pass 3:** Tightened the `TestModel` plan so `scripted_responses` is a required public record on the wrapper rather than an optional best-effort reconstruction from OpenHands internals.
4. **Pass 4:** Preserved the current `LLM` logging defaults explicitly in both the API-backed and subscription-backed construction paths so the refactor does not silently drop runtime logging behavior.
5. **Pass 5:** Removed `pyflow/models.py` from the implementation scope entirely and switched `Model.subscription(...)` / `Model.test(...)` from classmethods to staticmethods, because they do not depend on `cls` and should always return concrete wrapper types.

## Testing

Testing for this task should focus on the new public model contract, the new shared-`LLM` runtime semantics, and the places where the repository currently assumes `build_llm()` or recipe-style `TestModel` construction. The most important branching point is the API constructor surface: if `Model(...)` survives pyright cleanly, tests should assert that public form; if not, tests should assert `Model.from_api(...)` instead and must not keep redundant coverage for the rejected alternative.

### File: `tests/test_runtime.py`

Add or rewrite tests to cover the following cases.

- **Chosen API constructor returns `AIModel`**
  Verify the selected public API-backed constructor surface:
  - if the preferred path ships, `Model(name=..., api_key=..., ...)` returns `AIModel`
  - if the fallback ships, `Model.from_api(name=..., api_key=..., ...)` returns `AIModel`

- **API-backed constructor maps fields onto the owned `LLM`**
  Verify that the wrapped `model.llm` receives the expected values for:
  - `model`
  - `base_url`
  - `api_key`
  - `max_input_tokens`
  - `max_output_tokens`
  - `log_completions`
  - `log_completions_folder`

- **Direct `AIModel(llm=...)` wrapping preserves identity**
  Verify that passing an existing OpenHands `LLM` into `AIModel(llm=...)` stores and exposes that exact object via `model.llm`.

- **`Model.subscription(...)` constructs immediately and returns `AIModel`**
  Monkeypatch `pyflow.model.LLM.subscription_login` to return a sentinel `LLM`.
  Verify:
  - the helper is called during `Model.subscription(...)`
  - the returned value is `AIModel`
  - `model.llm is sentinel_llm`
  - the subscription path passes through the selected public kwargs and the pyflow logging defaults

- **`Model.test(...)` returns `TestModel` with a preserved public script**
  Verify:
  - the returned object is `TestModel`
  - `model.llm` is a `TestLLM`
  - `model.scripted_responses` exactly matches the original configured tuple

- **`TestModel(llm=..., scripted_responses=...)` preserves both wrapper fields**
  Verify that direct wrapper construction keeps:
  - the exact supplied `TestLLM` instance
  - the exact supplied public scripted-response record

- **`TestModel.scripted_responses` stays stable while the wrapped queue is consumed**
  Build a `TestModel` through `Model.test(...)`, call the wrapped `model.llm.completion(...)`, and verify:
  - `model.llm.call_count` increases
  - `model.llm.remaining_responses` decreases
  - `model.scripted_responses` remains unchanged

- **Agent runtime uses the owned `LLM` directly**
  Build an `AIModel` or `TestModel`, construct an OpenHands agent through `Agent._build_openhands_agent()`, and verify `openhands_agent.llm is model.llm`.

- **Two fresh runtime executions through one model share one `LLM`**
  Run two independent requests through the same pyflow model and verify that the resulting runtime path continues to use the same owned `model.llm`. The assertion should focus on `LLM` identity sharing, not on session continuation.

- **Session continuation tests stay green without `build_llm()` counters**
  Keep the current continuation coverage, but remove the `CountingModel`-style counter checks.
  Verify only the still-relevant properties:
  - continuation reuses the same `Session`
  - continuation reuses the same conversation
  - agent-level/global-context continuation behavior stays unchanged

- **Obsolete `build_llm()` tests are removed**
  Delete the current tests that encode the old builder contract rather than rewriting them into compatibility tests:
  - `test_ai_model_build_llm_maps_fields`
  - `test_test_model_build_llm_uses_scripted_responses`
  - `test_session_continuation_does_not_build_fresh_llm`
  - `CountingModel`

### File: `tests/test_tools.py`

Update test setup helpers and runtime tool-loop tests to use the new test-model surface.

- **Helper constructors use `Model.test(...)`**
  Replace local helper paths such as `_empty_test_model()` with `Model.test(...)` so the file reflects the public API.

- **Tool execution still works with owned `TestLLM` models**
  Keep existing tool-loop assertions intact while updating the model-construction path. This confirms that moving from builder-style models to owned-`LLM` models does not alter tool execution semantics.

- **Session continuation still keeps request-attached tools prompt-only**
  Keep the existing assertion, but ensure the setup uses the new `Model.test(...)` surface.

### File: `tests/test_notebook_visualizer.py`

Update notebook-only helpers to the new model surface without changing notebook rendering assertions.

- **Notebook agent setup uses `Model.test(...)`**
  Replace direct `TestModel(scripted_responses=...)` construction in helper functions with `Model.test(...)`.

- **Notebook transcript rendering behavior stays unchanged**
  Keep the current HTML/live-update assertions exactly as they are after the model-construction rewrite.

### File: `tests/test_runtime_logging.py`

Update the single runtime setup path that still instantiates the old recipe-style `TestModel`.

- **Runtime logging policy works with `Model.test(...)`**
  Replace `TestModel(scripted_responses=(), name="unused")` with `Model.test(scripted_responses=(), name="unused")` and keep the logging assertions unchanged.

### Type-checking verification

The type checker is a required verification surface for this task because the `Model(...)` versus `Model.from_api(...)` choice depends on whether the preferred constructor can be expressed honestly.

- **Preferred constructor typing is accepted, or the fallback is used instead**
  Verify with pyright that:
  - the shipped public constructor path type-checks without `# type: ignore`
  - direct `AIModel(llm=...)` and `TestModel(llm=..., scripted_responses=...)` construction type-check cleanly
  - `Model.subscription(...)` and `Model.test(...)` resolve to concrete return types

If the preferred `Model(...)` path fails this check, the implementation must switch to `Model.from_api(...)`, and the runtime tests should cover only the fallback public form.

### Non-trivial test-suite adjustments

- Update helper constructors across the test suite so they centralize on `Model.test(...)` and do not keep old builder-style patterns alive accidentally.
- Use monkeypatching for `LLM.subscription_login(...)` so the subscription path is tested without real authentication or browser side effects.
- Do not add compatibility tests for `build_llm()`; the purpose of this task is to remove that contract, not preserve it behind deprecated coverage.
- No changes are needed in `pyflow/models.py`, and no tests should be added for that file as part of this task.

### Review notes

1. **Pass 1:** Centered the testing section on the public semantic shift, not the mechanical refactor, so the tests verify owned-`LLM` identity and public constructors rather than internal implementation details.
2. **Pass 2:** Made the constructor-path tests conditional on the `Model(...)` versus `Model.from_api(...)` decision so the suite does not accidentally require both public APIs at once.
3. **Pass 3:** Added explicit coverage for `TestModel.scripted_responses` stability during `TestLLM` queue consumption, because that is the new public guarantee replacing any need to inspect OpenHands internals.
4. **Pass 4:** Kept non-runtime suites (`tests/test_tools.py`, `tests/test_notebook_visualizer.py`, `tests/test_runtime_logging.py`) intentionally narrow: update only their model setup, keep their behavioral assertions unchanged.
