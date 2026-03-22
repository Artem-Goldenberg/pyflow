# Add Subscription-Backed Model Construction to `AIModel`

## Summary

Pyflow already has a working runtime model layer, but it only exposes API-key-backed provider configuration through `AIModel(...)` and deterministic offline execution through `TestModel`. It does not yet provide a pyflow-native way to construct a model that authenticates through an OpenHands subscription login flow instead of a direct API key.

This task adds a first-class subscription-backed model construction path while preserving the existing `Model -> build_llm() -> Agent` boundary. The public entry point should be `AIModel.from_subscription(...)`, and the runtime should use a dedicated subscription-backed model configuration object rather than overloading the existing API-key configuration shape. After implementation, testing must confirm the new construction flow, runtime compatibility with `Agent` and `request >> model`, immutability and side-effect timing, and correct rejection or delegation for unsupported subscription combinations.

## Introduction

### Prerequisites

- **Documentation**
  - `AGENTS.md`
    - `Core Abstractions`
    - `Conventions`
    - `Testing`
    This document matters because it defines the current `Model`/`Agent` direction, the immutability expectations, and the project rule that ambiguous API decisions must be surfaced explicitly.
  - `ARCHITECTURE.md`
    - `Component Map`, especially `Runtime Model Layer`
    - `Data Flow`
    This document matters because it states that pyflow runtime models are the configuration boundary that builds OpenHands `LLM` instances for execution.
  - `README.md`
    - `Status`
    - `Minimal pyflow Example`
    - `Offline Runtime Tests`
    This document matters because it documents the current public story: `AIModel` is the real-provider model path and `TestModel` is the offline scripted path.
  - Installed OpenHands SDK API
    - `openhands.sdk.LLM`
    - `openhands.sdk.LLM.subscription_login(...)`
    - `openhands.sdk.LLM.is_subscription`
    This API matters because pyflow should wrap the existing OpenHands subscription capability instead of inventing a separate transport model.
  - `IMPLEMENTATION_PLAN.md`
    - `Current Status`
    - `Cross-Cutting Quality Gates`
    This file matters because it confirms that `Agent/Model` bootstrap work exists and that typing/runtime coverage remains a required quality gate.

- **Related code**
  - `pyflow/model.py` — current `Model`, `AIModel`, and `TestModel` definitions and the only existing `build_llm()` implementations
  - `pyflow/agent.py` — runtime path that consumes `Model.build_llm()` and must remain unchanged in user-facing semantics
  - `pyflow/__init__.py` — current public export surface for model types
  - `tests/test_runtime.py` — existing runtime-model behavior coverage
  - `pyflow/models.py` — current placeholder that mentions `LLM.subscription_login()` but is not a real public API

### Problem

Currently, pyflow already has the core runtime shape we want: an abstract `Model` builds an OpenHands `LLM`, `Agent` consumes that `LLM`, and users can execute requests through either `Agent(model=...)` or `request >> model`.

But the real-provider path is incomplete. `AIModel` currently represents only direct provider configuration with `name`, `api_key`, optional `base_url`, and token limits, and `build_llm()` always constructs `LLM(...)` directly. Although the installed OpenHands SDK already supports subscription-authenticated models through `LLM.subscription_login(...)`, pyflow has no first-class way to represent or construct that mode. The repository only contains a non-functional placeholder comment in `pyflow/models.py`, so subscription-backed execution is neither modeled nor documented at the pyflow layer.

This task solves the problem by adding an explicit subscription-backed construction path to the pyflow model layer. Users should be able to ask pyflow for a subscription-backed model in the same way they currently ask for an API-key-backed model, while pyflow keeps subscription authentication separate from the existing `AIModel(...)` API-key configuration shape.

### Task

This task belongs to the runtime model layer. Pyflow already treats model objects as immutable runtime configuration that delays OpenHands object creation until `build_llm()` is called. That boundary is valuable and must remain intact. The task is therefore not “make `AIModel` call a different OpenHands helper immediately”; it is “extend the pyflow model API so subscription-backed authentication is representable, constructible, and executable through the same existing runtime sink flow.”

The required behavior is:

- users must be able to create a subscription-backed pyflow model by calling `AIModel.from_subscription(...)`
- `AIModel.from_subscription(...)` must be a pyflow-level named constructor that wraps OpenHands subscription login behavior; it is not required to mirror the upstream method name `LLM.subscription_login(...)`
- the object returned by `AIModel.from_subscription(...)` must still be a pyflow `Model`, so it works anywhere a `Model` works today
- subscription-backed configuration must be modeled separately from API-key-backed configuration rather than reusing `AIModel(...)` fields like `api_key` or `base_url` for a different authentication mode
- constructing the pyflow model must remain side-effect-free; subscription login, token refresh, browser opening, or other authentication activity must not happen at constructor time and must happen only when the OpenHands `LLM` is actually built for execution
- the runtime behavior of `Agent(model=...)`, `request >> model`, and session continuation must remain unchanged aside from the new ability to use a subscription-backed model as the `Model`
- pyflow must not claim broader subscription support than the installed OpenHands SDK actually provides; unsupported vendors or models must fail clearly, preferably by delegating validation to the upstream OpenHands subscription flow

The scope of this task is exactly the following:

- add the new user-facing `AIModel.from_subscription(...)` construction path
- introduce a distinct public model type for subscription-backed configuration
- make the new model type build an OpenHands `LLM` through `LLM.subscription_login(...)`
- export the new model type from `pyflow`
- document the intended user-facing difference between API-key-backed and subscription-backed model construction

The scope explicitly excludes:

- changing `Model.build_llm()` as the runtime abstraction boundary
- changing `Agent`, `Session`, request composition, tools, or display behavior
- adding pyflow-owned credential storage, token caching, or OAuth UX beyond what OpenHands already provides
- inventing vendor-specific subscription support that is not already supported by OpenHands
- redesigning `AIModel(...)` into a generic catch-all constructor for every possible authentication mode

The completion of this task must produce the following user-facing changes.

#### 1. `AIModel.from_subscription(...)` becomes the ergonomic constructor for subscription-backed runtime models

Current usage only supports API-key-backed configuration:

```python
from pydantic import SecretStr
from pyflow import AIModel

model = AIModel(
    name="openai/gpt-4.1",
    api_key=SecretStr("..."),
    base_url="https://api.openai.com/v1",
)
```

After this task, users must also be able to construct a subscription-backed model through a named constructor on `AIModel`.

Illustrative example:

```python
from pyflow import AIModel

model = AIModel.from_subscription(
    vendor="openai",
    model="gpt-5.2-codex",
    force_login=False,
    open_browser=True,
    max_output_tokens=8192,
)
```

Expected behavior:

- `AIModel.from_subscription(...)` is the preferred public entry point for subscription-backed model construction
- the returned object is a pyflow `Model`
- users do not need to import or call `openhands.sdk.LLM.subscription_login(...)` directly to use subscription-backed execution through pyflow
- the constructor accepts subscription-relevant options and pass-through OpenHands `LLM` configuration that remains meaningful in subscription mode, such as token or reasoning-related limits
- the constructor does not require API-key-specific inputs such as `api_key`

#### 2. Subscription-backed configuration is represented by a distinct public model type

This task introduces the following new public API names:

- `AIModel.from_subscription`
- `SubscriptionModel`

The new constructor on `AIModel` is an ergonomic entry point, but the resulting configuration must remain explicit in the type system and public API.

Illustrative example:

```python
from pyflow import AIModel, Model, SubscriptionModel

model = AIModel.from_subscription(
    vendor="openai",
    model="gpt-5.2-codex",
)

assert isinstance(model, SubscriptionModel)
assert isinstance(model, Model)
```

Expected behavior:

- pyflow continues to have a clear distinction between API-key-backed and subscription-backed runtime configuration
- users and tests can refer to the subscription-backed type directly when they need type clarity or intent clarity
- `AIModel(...)` remains the API-key-backed configuration surface and is not silently repurposed to mean “sometimes API key, sometimes subscription”

#### 3. Model construction stays pure; authentication happens only at runtime

Pyflow currently models runtime configuration as immutable data that becomes a live OpenHands object only when execution begins. The new subscription path must preserve that rule.

Illustrative example:

```python
from pyflow import AIModel

model = AIModel.from_subscription(
    vendor="openai",
    model="gpt-5.2-codex",
)

# No browser opening or login side effects should happen here.
session = "Refactor the module safely." >> model
```

Expected behavior:

- constructing the pyflow model object is side-effect-free
- any browser-opening, cached-credential lookup, token refresh, or login prompt happens only when the runtime actually builds the OpenHands `LLM`
- repeated executions may still rely on OpenHands credential reuse or refresh behavior, but that behavior is delegated to OpenHands rather than reimplemented by pyflow

#### 4. The new model works everywhere a pyflow `Model` already works

This task is about adding a new model construction mode, not introducing a new execution path.

Illustrative example:

```python
from pyflow import AIModel, Agent

model = AIModel.from_subscription(
    vendor="openai",
    model="gpt-5.2-codex",
)

agent = Agent(model=model)
session = "Audit the package layout." >> agent
session = "Now implement the smallest safe fix." >> session
```

Expected behavior:

- `Agent(model=model)` works with the returned subscription-backed model object
- `request >> model` also works through the existing `Model.__rrshift__` path
- session continuation semantics remain unchanged because the new behavior stays inside the existing `Model.build_llm()` boundary

#### 5. Unsupported subscription combinations fail clearly instead of being guessed by pyflow

OpenHands already defines which subscription vendors and models it supports. Pyflow must not add ambiguous fallback behavior here.

Illustrative example:

```python
from pyflow import AIModel

model = AIModel.from_subscription(
    vendor="some-unsupported-vendor",
    model="unknown-model",
)
```

Expected behavior:

- pyflow does not silently remap unsupported vendors or models
- failure should be clear and early in the runtime path where the OpenHands `LLM` is built
- the error should remain recognizably tied to upstream OpenHands support rather than looking like pyflow invented its own subscription matrix

#### Notes

- The pyflow public constructor name is intentionally `AIModel.from_subscription(...)` even though the upstream OpenHands helper is named `LLM.subscription_login(...)`. The pyflow API should read like model construction, not like a direct authentication procedure.
- The working design assumption for this plan is that `SubscriptionModel` is a real public type, not a private implementation detail. That keeps the two authentication modes explicit and avoids overloading `AIModel(...)` with fields that only make sense for one mode.
- `pyflow/models.py` is currently only a placeholder and must not be treated as an existing supported public surface for subscription-backed execution.
- This task does not require pyflow to expose every single OpenHands `LLM` constructor keyword immediately if some of them are clearly unrelated to the intended public story. The public requirement is that subscription-relevant configuration remains available without collapsing the API-key-backed and subscription-backed models into one ambiguous constructor.

### Review notes

1. Tightened the task to stay within the existing `Model.build_llm()` boundary instead of treating subscription login as a special execution path.
2. Made the current-vs-desired behavior explicit by contrasting the existing API-key-backed `AIModel(...)` with the missing subscription-backed pyflow API and the dead placeholder in `pyflow/models.py`.
3. Added an explicit purity requirement so model construction remains side-effect-free and browser/login behavior occurs only at runtime.
4. Recorded the recommended public API names and the design assumption that `AIModel.from_subscription(...)` returns a distinct `SubscriptionModel`, because that is the main architectural decision the later implementation plan will depend on.
