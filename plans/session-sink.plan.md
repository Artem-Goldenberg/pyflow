[DONE]

# Introduce a Reusable Session Sink for `request >> agent` and `request >> session`

## Summary

Pyflow already supports executing composed requests through runtime sinks, but each execution currently returns a raw OpenHands conversation object that is useful for inspection and not for continuing the session through the same `>>` DSL. `Agent` and `Model` runs create or delegate to a fresh OpenHands conversation and return `BaseConversation`, so follow-up requests cannot be expressed as `request >> session` in a typed pyflow-native way.   

This task introduces a thin pyflow-owned **Session** wrapper around the underlying OpenHands conversation and makes it the standard runtime result of `request >> agent` and `request >> model`. The new object must itself be a sink, so users can continue the same conversation by writing `request >> session` anywhere, including scripts, tests, REPLs, and future notebook integrations. After implementation, testing must confirm correct return types, correct continuation semantics, preservation of existing request rendering/tool behavior, and compatibility with current sink-based DSL execution.  

## Introduction

### Prerequisites

* **Documentation**

  * `ARCHITECTURE.md`

    * Design Principles
    * Component Map
    * Data Flow
    * Planned Extensions
      The architecture document is important because it states that pyflow currently keeps the DSL separate from runtime execution, that sinks execute requests, and that `request >> agent` currently returns an OpenHands conversation. 
  * `AGENTS.md`

    * Core Abstractions
    * Conventions
    * Testing
    * Near-Term Priorities
      This file is important because it defines the project’s typing/style conventions and confirms that session visibility and interactive intervention are intended project directions. 
  * `README.md`

    * Status
    * Minimal pyflow Example
    * Notes
      This file is important because it documents the current public story: pyflow has OpenHands execution wiring with conversation return values, while interactive workflows are still planned. 

* **Related code**

  * `pyflow/sink.py` — current sink contract and return type (`BaseConversation`) 
  * `pyflow/agent.py` — current execution path, fresh `Conversation` creation, and raw conversation return 
  * `pyflow/model.py` — model-level sink execution delegates through `Agent` and also returns `BaseConversation` 
  * `pyflow/request.py` — request-side `>>` behavior toward sinks 
  * `pyflow/steps.py` — step-side `>>` behavior toward sinks 
  * `pyflow/__init__.py` — current public exports; no pyflow session type exists yet 
  * `tests/test_runtime.py` — existing runtime and sink behavior tests that will need expansion or adjustment 

### Problem

Currently, pyflow already has a clean immutable request DSL and a working sink execution model: `Step` and `Request` forward execution to sink objects via `__rrshift__`, `Agent` executes requests through OpenHands, and `Model` delegates runtime execution through `Agent`.    

But the runtime layer still returns raw OpenHands `BaseConversation` objects, and `Agent.run()` currently creates a fresh OpenHands `Conversation` for every run. Because the returned value is not a pyflow sink object, the DSL cannot express session continuation as `request >> conversation` or `request >> session`; the user must start a new execution through an `Agent` or `Model` instead.   

This task solves the problem by inserting one thin pyflow runtime abstraction between the DSL and the underlying OpenHands conversation: a reusable **Session** object. The Session will wrap the OpenHands conversation, preserve pyflow-level typing and ownership, and act as both the return value of execution and the sink target for continuation.

### Task

Pyflow currently has two distinct layers relevant to this change:

1. the **composition layer**, where users build immutable requests with `>>` and `@`
2. the **runtime sink layer**, where those requests are executed by objects such as `Agent` and `Model`  

This task belongs entirely to the runtime sink layer. It must not change how requests, steps, contexts, or tools are composed. Instead, it must change what runtime execution returns and what kinds of objects can continue an execution.

The required task is to introduce a new public pyflow runtime type named **Session** and make it the standard execution result of pyflow runtime sinks. The Session must be a thin wrapper around the underlying OpenHands conversation. “Thin” here means it must preserve the OpenHands conversation as the underlying execution engine and state holder, while exposing only the pyflow behavior needed to:

* identify the object as the result of a pyflow execution
* continue the same conversation through `request >> session`
* retain access to the underlying OpenHands conversation for inspection and integration

The scope of this task is exactly the following:

* `request >> agent` must return a pyflow `Session`
* `request >> model` must return a pyflow `Session`
* `step >> agent` and `step >> model` must also return a pyflow `Session`, because steps already execute through the same sink path  
* `request >> session` must append a new user request to the same underlying conversation and continue execution
* `step >> session` must do the same after coercion into a one-step request
* the Session must be publicly exported from `pyflow`
* the Session must remain compatible with future notebook-global reuse, but notebook-specific global state is **not** part of this task

The scope explicitly excludes:

* changes to request composition syntax
* backend abstraction away from OpenHands
* redesign of tool execution or request rendering

The desired behavior is user-facing and must be unambiguous.

The completion of this task should produce the following 
user-facing changes:

#### 1. Runtime execution returns `Session`, not raw OpenHands conversation

Current usage:

```python
from pyflow import Agent

agent = Agent(model=model)
conversation = request >> agent
```

After this task, the returned object must be a pyflow `Session`, not a raw `BaseConversation`. The Session may expose the underlying OpenHands conversation via an attribute or documented accessor, but the public semantic result of pyflow execution is the Session itself.

Illustrative example:

```python
from pyflow import Agent, Session

agent = Agent(model=model)
session = request >> agent

assert isinstance(session, Session)
```

Expected behavior:

* the execution still runs immediately
* the first request still produces the same agent-side effect as today: a completed OpenHands run for that request
* the returned value is now a pyflow-owned resumable handle rather than a backend-native object

#### 2. The returned `Session` is itself a sink

This is the main behavior change.

Illustrative example:

```python
session = "Inspect the parser design." >> agent
"Now refactor only the tokenizer part." >> session
```

Expected behavior:

* the second line must continue the same underlying OpenHands conversation created by the first line
* the new prompt must be appended as a new user request, not executed in a fresh conversation
* the result of the second line must again be a `Session`
* this may be the same Session object mutated internally, or a new Session object wrapping the same continued conversation, but this behavior must be consistent and documented; for this task, the intended behavior is that the Session object itself is reused and returned again

#### 3. `Model` remains a convenience sink, but now returns `Session` too

Current `Model.__rrshift__` delegates to `Agent(model=self).__rrshift__(lhs)`, so the `Model` path must inherit the same new behavior. 

Illustrative example:

```python
session = "Fix the failing tests." >> model
"Only modify production code if tests require it." >> session
```

Expected behavior:

* the first line creates and runs a pyflow Session through an implicit Agent
* the second line continues that same Session
* users do not need to know whether the Session originally came from an explicit `Agent` or a `Model`

#### 4. Backend access must remain possible

The Session is thin, so users and tests must still be able to inspect the underlying OpenHands conversation data. This is required because existing runtime tests and future integrations rely on backend conversation state and events. For example, current tests inspect OpenHands runtime objects and event streams after execution. 

Expected behavior:

* Session must provide a stable, documented way to access the wrapped OpenHands conversation
* the task does not require hiding OpenHands internals; it only requires that pyflow execution returns a pyflow-native object first

#### Illustrative end-to-end example

```python
from pyflow import Agent, Session, tests

agent = Agent(model=model)

session = (
    ("Fix the parser bug." >> tests("unit"))
    >> agent
)

assert isinstance(session, Session)

session = "Now clean up duplicated helpers." >> session
session = "Run only focused follow-up changes." >> session

raw_conversation = session.conversation  # illustrative attribute name
```

In this example:

* `Session` is a pyflow wrapper
* `session.conversation` is illustrative naming only; the exact accessor name belongs to implementation detail, but equivalent backend access is required
* the second and third prompts continue the same session
* no notebook-specific behavior is assumed

#### Notes

* The wrapper must be named **Session**, not **Conversation**. OpenHands already owns the public name `Conversation`, and pyflow must not introduce a second public type with the same conceptual name but different semantics.
* Existing request composition semantics must remain unchanged. In particular:

  * `Step >> Step` must still produce a `Request`
  * `Request >> Step` must still extend a `Request`
  * `@` attachment behavior must remain unchanged
  * only sink execution changes, by returning `Session` instead of raw `BaseConversation`  

## Task introduction review notes

1. **Pass 1:** Replaced the notebook-oriented framing with a general runtime framing, because your clarified requirement is `request >> session` everywhere, not just in notebooks.
2. **Pass 2:** Moved the naming requirement and “do not change DSL composition semantics” requirement out of the user-facing change list and into a dedicated **Notes** subsection at the end of **Task**.
3. **Pass 3:** Tightened the problem statement so it explicitly distinguishes current behavior from desired behavior: current sinks return `BaseConversation`, `Agent.run()` creates a fresh backend conversation per run, and the new `Session` exists to widen only the runtime result/continuation contract.  

- Changed the wrapper name from “Conversation” to **Session** to avoid a public-name collision with OpenHands `Conversation` and to make the pyflow-owned role clearer.
- Reframed the task as a **general runtime change**, not a notebook feature, because the desired `request >> session` behavior must work everywhere.
- Tightened the scope so that notebook-global reuse, rendering, and approval UX are explicitly out of scope for this task.
- Made the current-runtime baseline explicit: sinks return `BaseConversation`, `Agent.run()` creates a fresh OpenHands conversation per run, and `Model` delegates through `Agent`. This avoids mixing desired behavior with existing behavior.   
- Clarified that DSL composition must remain unchanged and only sink execution results/continuation semantics are being widened.
- Clarified that the Session must remain thin and preserve access to the underlying OpenHands conversation for inspection and future integrations.


## Implementation

The implementation should be split into four goals:

1. add a first-class `Session` runtime object
2. make `Agent` and `Model` return `Session`
3. fix sink/operator typing so `request >> session` and `step >> session` type correctly
4. preserve existing backend behavior while widening continuation semantics

The current runtime boundary is the right place for this work: the DSL layer already composes immutable `Request` and `Step` objects, while runtime execution happens through sinks such as `Agent` and `Model`. Today, that sink layer returns raw OpenHands conversations and creates a fresh backend conversation for every `Agent.run()` call.   

### 1. Add a first-class `Session` runtime object

#### 1.1 Create `pyflow/session.py`

Add a new module `pyflow/session.py` containing the public `Session` class.

The class should be a thin pyflow-owned wrapper around the live OpenHands conversation created by `Agent.run()`. It should not try to replace or reimplement backend state management. Its job is only to:

- hold the wrapped backend conversation
- remember the originating pyflow `Agent`
- implement `__rrshift__` so the session itself is a sink

Use a small dataclass. It does **not** need to be frozen, because this is a runtime handle that appends new turns to the same conversation.

Recommended shape:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openhands.sdk import Conversation

from pyflow.request import Request
from pyflow.sink import RequestInput
from pyflow.tooling import collect_request_tools, compile_openhands_tools

if TYPE_CHECKING:
    from pyflow.agent import Agent


@dataclass(kw_only=True)
class Session:
    _agent: Agent
    conversation: Conversation

    def __rrshift__(self, lhs: RequestInput) -> Session:
        request = _coerce_request(lhs)
        self._attach_request_tools(request)
        self.conversation.send_message(self._agent._render_message(request))
        self.conversation.run()
        return self
```

Important details:

* `conversation` should be the public backend accessor.
* The public accessor should be explicit; do **not** use `__getattr__` passthrough for the MVP.
* `__rrshift__` must return the same `Session` object after continuation.
* The session should store the original `Agent`, because later messages must still be rendered with that agent’s global contexts and prompt formatting. The current rendering logic lives in `Agent._render_message()`. 

#### 1.2 Attach unknown request tools immediately before continuation runs

This is the most important implementation nuance.

Today, `Agent._build_openhands_agent()` compiles the tool list from:

* `agent.tools`
* request-attached tools collected from the specific request being executed

and passes that merged tool list into a freshly constructed backend agent.  

That means plain “append a new message and run again” is **not enough** for `request >> session`, because later requests may attach new tools that were not present when the backend conversation was first created.

`Session` should not track cumulative request tools. Instead, on every continued turn it must inspect the current request, compile tool descriptions for that request, and append only those tool descriptions whose names are not already present on the live backend agent.

Add a private helper inside `Session`, for example:

```python
def _attach_request_tools(self, request: Request) -> None:
    tool_specs = compile_openhands_tools(
        self._agent.tools,
        collect_request_tools(request),
    )
    known_names = {tool.name for tool in self.conversation.agent.tools}
    for tool_spec in tool_specs:
        if tool_spec.name in known_names:
            continue
        self.conversation.agent.tools.append(tool_spec)
        known_names.add(tool_spec.name)
```

Implementation rules:

* do not store request-tool state on `Session`
* for each continuation request, collect only that request’s attached tools and compile their OpenHands tool descriptions
* append tool descriptions only when the tool name is not already present on the live backend agent
* keep this backend-agent mutation isolated in one helper so any OpenHands SDK-specific field access is localized

This preserves the requested behavior: unknown-before tools become available right before the turn that needs them, without adding session-level tool tracking.  

### 2. Make runtime sinks return `Session`

#### 2.1 Update `pyflow/agent.py`

`Agent.run()` currently:

1. creates a fresh backend `Conversation`
2. sends the rendered message
3. runs the conversation
4. returns the raw backend conversation 

Change it to return `Session` instead.

Recommended refactor:

* keep `_render_message()` unchanged
* keep `_build_openhands_agent()` unchanged for the initial turn
* change `run()` to:

  1. coerce/build the initial backend `Conversation`
  2. send the first message
  3. run it
  4. return `Session(_agent=self, conversation=conversation)`

Suggested shape:

```python
def run(self, request: Request) -> Session:
    conversation = Conversation(
        agent=self._build_openhands_agent(request),
        workspace=self.workspace,
    )
    conversation.send_message(self._render_message(request))
    conversation.run()
    return Session(
        _agent=self,
        conversation=conversation,
    )
```

Also change `Agent.__rrshift__` to return `Session` and keep `_coerce_request(...)` as the normalization helper for request-like input. The current private request coercion logic is already correct for both `Request` and single-step input. 

#### 2.2 Update `pyflow/model.py`

`Model.__rrshift__` currently delegates to `Agent(model=self).__rrshift__(lhs)` and is typed as returning `BaseConversation`. 

Keep the delegation pattern, but change the return type to `Session`.

No behavioral change is needed beyond the return type widening, because the delegated `Agent` path will already produce a `Session` after the `Agent` changes.

#### 2.3 Export `Session` publicly

Update `pyflow/__init__.py` to export `Session` alongside `Agent`, `Model`, `Request`, `Step`, and the tool/context helpers. There is currently no public session abstraction in the package exports. 

Also update the module-level docstring/comments where needed so the public story becomes:

* compose a request
* execute it via `agent` or `model`
* continue it via the returned `Session`

### 3. Fix sink/operator typing with concrete `Session` results

This goal is required so pyright matches the new runtime contract while keeping DSL composition unchanged.

Right now:

* `RequestSink` is defined as returning `BaseConversation` 
* `Request.__rshift__` is annotated as returning `Request` even when the RHS is actually a sink 
* `Step.__rshift__` is also annotated as returning `Request` even when the RHS is a sink 

That is too narrow once `Session` becomes the standard execution result. 

#### 3.1 Set `RequestSink` to return `Session` in `pyflow/sink.py`

Change the sink protocol to the concrete return type.

Recommended shape:

```python
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pyflow.session import Session


class RequestSink(Protocol):
    def __rrshift__(self, lhs: RequestInput) -> Session: ...
```

Keep `RequestInput = Request | StepInput` unchanged.

#### 3.2 Add concrete overloads in `pyflow/request.py`

`Request.__rshift__` should have overloads like:

```python
@overload
def __rshift__(self, rhs: StepInput) -> Request: ...

@overload
def __rshift__(self, rhs: RequestSink) -> Session: ...
```

Implementation guidance:

* preserve current step-append behavior exactly
* preserve current operator fallback semantics for sink execution
* annotate the implementation return as `Request | Session`

If pyright requires explicit runtime dispatch, add `@runtime_checkable` to `RequestSink` and branch on sink-vs-step explicitly.

#### 3.3 Add concrete overloads in `pyflow/steps.py`

Apply the same pattern to `Step.__rshift__`.

This keeps:

* `step >> step` returning `Request`
* `step >> agent`, `step >> model`, and `step >> session` returning `Session`

Do **not** change `Step.__rrshift__`, `Request.__matmul__`, or any composition semantics. The composition layer must remain unchanged, as already required by the first part of the plan. The current DSL behavior around immutable `Request`/`Step` composition should remain intact.   

### 4. Update docs and keep boundaries clear

#### 4.1 Update `README.md`

The README currently shows:

```python
conversation = request >> agent
```

and describes the runtime as “OpenHands execution wiring with conversation return values.” 

Update it to the new public story:

```python
session = request >> agent
session = "Follow up." >> session
raw_conversation = session.conversation
```

This should appear in:

* the minimal pyflow example
* the status section wording
* any note that currently implies the raw backend conversation is the direct public result

#### 4.2 Update `ARCHITECTURE.md`

The architecture doc currently says the agent layer “supports sink execution (`request >> agent`) and returns OpenHands conversation.” 

Update it so the agent layer returns `Session`, while `Session` wraps the underlying OpenHands conversation. Also update the data-flow section so the runtime result is described as a pyflow session handle rather than direct backend state.

#### 4.3 Keep the wrapper intentionally narrow

The MVP wrapper should expose:

* session continuation via `__rrshift__`
* explicit backend access via `.conversation`

It should not add:

* magic backend method forwarding
* notebook-global state
* renderer logic
* CLI/interactivity hooks

That keeps the runtime boundary stable and matches the current architecture principle of widening capabilities iteratively rather than collapsing layers together. 

## Testing

The project conventions already require `pytest`, regression coverage for typing-sensitive operator behavior, and a pyright run after Python changes. 

### `tests/test_runtime.py`

Keep the existing sink operator tests and expand this file with the new session-focused runtime cases.

#### Test case: `request >> agent` returns `Session`

Property:

* executing a request through `Agent` returns `Session`
* `Session.conversation` is the wrapped backend conversation object
* the initial run still executes successfully

#### Test case: `request >> model` returns `Session`

Property:

* executing through `Model` still works through the delegated runtime path
* the returned object is `Session`

#### Test case: `request >> session` reuses the same session object

Property:

* `session = "first" >> agent`
* `returned = "second" >> session`
* `returned is session`
* `returned.conversation is session.conversation`

This verifies the “same session object reused and returned again” rule from the task spec.

#### Test case: `step >> session` coerces through the same continuation path

Property:

* continuing a session with a single step input, not only a full `Request`, still works
* the request coercion path remains consistent with current `Agent.__rrshift__` behavior

#### Test case: continuation does not build a fresh backend LLM/agent

Property:

* create a small spy model subclass that counts `build_llm()` calls
* run one request through `agent`
* continue through `session`
* `build_llm()` must have been called exactly once

This is a non-trivial but very valuable regression test: it proves the continuation path reuses the live backend conversation rather than silently creating a new one.

#### Test case: `step >> agent` and `step >> model` return `Session`

Property:

* executing a single-step input through `Agent` returns `Session`
* executing a single-step input through `Model` returns `Session`
* the step input is still coerced through the same request path as `request >> sink`

This guards the concrete `RequestSink -> Session` typing update while preserving existing step coercion behavior. 

### `tests/test_tools.py`

This file already exercises request-attached tools, tool compilation, and tool execution through the OpenHands tool loop.  

Add the session-specific tool regression cases here.

#### Test case: session continuation attaches unknown request tools before run

Property:

* first request starts a session with no custom request-attached tool
* second request continues the session and attaches a custom tool
* the continued run is able to call that tool successfully
* the resulting wrapped backend conversation contains the expected action/observation events for that tool
* the newly attached tool name appears on `session.conversation.agent.tools`

This test is required because the current backend agent is built from request-attached tools at session creation time only. Without the continuation-time attachment step, a newly attached tool on the second turn would not be usable.  

#### Test case: re-attaching an already known tool does not duplicate backend tool descriptions

Property:

* attach a custom tool during one continuation turn
* continue with a later request that attaches the same tool again
* `session.conversation.agent.tools` still contains that tool name exactly once

This ensures the continuation path follows the “attach unknown-before tools only” rule. 

### `tests/test_request_dsl.py`

No new behavior should be added here unless pyright or runtime behavior reveals an operator regression.

This file is primarily about immutable DSL composition and precedence, and this task must not change those semantics. The current composition tests should continue passing unchanged. 

## Implementation and testing review notes

1. **Pass 1:** Kept the implementation centered on a concrete `Session` class in `pyflow/session.py`, with a narrow runtime responsibility: hold `Agent` + backend conversation and continue turns.
2. **Pass 2:** Removed session-level request tool state (`_request_tools`) and replaced it with per-request continuation-time attachment of only unknown tool descriptions immediately before sending the next message.
3. **Pass 3:** Simplified sink typing to the concrete contract `RequestSink.__rrshift__(...) -> Session` and updated `Request`/`Step` typing with concrete `Session` overloads, removing type-variable-based sink result typing.
4. **Pass 4:** Updated all code snippets to avoid quoted type annotations in postponed-evaluation contexts (`from __future__ import annotations` + `TYPE_CHECKING` imports).

DONE
