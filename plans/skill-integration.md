# OpenHands Skill Integration and Agent-Scoped Attachments

## Summary

Pyflow already has an immutable request DSL and an OpenHands-backed runtime, but it does not yet expose OpenHands skills as first-class attachable runtime state. This task adds skill attachments to the framework, makes `Agent` support `@` composition for agent-scoped skills and tools, and tightens request/session attachments so they may only reference skills and tools that are already loaded into the active agent or session. After implementation, testing must confirm skill loading from OpenHands SDK sources, correct agent attachment ergonomics, strict erroring for unloaded skill/tool references in requests and sessions, and no regressions in existing request composition behavior.

## Introduction

### Prerequisites

- **Documentation**:
  - [Architecture overview](ARCHITECTURE.md)
  - [Project instructions](AGENTS.md)
  - [OpenHands SDK docs](https://docs.openhands.dev/sdk)
  - [OpenHands Agent Skills & Context guide](https://docs.openhands.dev/sdk/guides/skill)
- **Related code**:
  - [Agent runtime adapter](pyflow/agent.py)
  - [Context base types](pyflow/context.py)
  - [Request composition](pyflow/request.py)
  - [Step composition](pyflow/steps.py)
  - [Tool DSL and OpenHands compilation](pyflow/tooling.py)
  - [Tool behavior tests](tests/test_tools.py)

### Problem

Pyflow now successfully supports immutable request composition, attachable step contexts, and agent-level tool registration for OpenHands execution. But it still lacks first-class OpenHands skill integration, `Agent` itself cannot participate in `@` composition, and request-attached tools are currently prompt-only hints even when the corresponding tools were never loaded into the active runtime.

Adding OpenHands skills to the adapter solves the missing backend capability boundary and lets the DSL express skills using the same attachment style as other runtime features. Tightening request/session attachments solves the current mismatch where a request can mention a skill or tool that the active agent/session does not actually provide.

### Task

This task belongs to the runtime composition boundary between the pyflow DSL and the OpenHands SDK adapter. The goal is to let users declare runtime-available skills on `Agent`, refer to those skills from requests and continued sessions, and make those references safe by requiring that they resolve against the active runtime rather than silently becoming prompt text.

The current task is to add OpenHands `Skill` integration without introducing a pyflow-defined `Skill` class, and to extend the attachment model so both skills and tools follow the same agent-scoped availability rule. The task must not broaden into new skill lifecycle management features, public skill installation commands, or dynamic mid-session mutation of the already-created OpenHands agent beyond what is required for the new attachment semantics.

The completed behavior must produce the following user-facing changes.

#### New public API names

- `SkillSet`
- `skills`

#### Agent-level attachment support

`Agent` must support `@` composition so users can add runtime-scoped skills and tools by creating a new agent value. The supported and recommended style is repeated assignment:

```python
from openhands.sdk.context import Skill

agent = Agent(model=model)
agent @= skills(".", "path/to/skill-folder", my_skill_obj)
agent @= tools("terminal", "read_file")
```

The examples above are illustrative with respect to the actual path values. The required behavior is:

- `skills(...)` is an attachable pyflow object, not a bare `list[Skill]`.
- The public parameter annotation of `skills(...)` must inline accepted inputs directly rather than introducing a `SkillInput` type alias.
- Accepted public inputs for `skills(...)` must include `str`, `Path`, and OpenHands `Skill` instances.
- `Agent @ skills(...)` must make those skills available to the OpenHands runtime for new sessions started from that agent.
- `Agent @ tools(...)` must continue to mean agent-scoped tool availability, but now through the same attachment style as skills.

#### Skill attachment behavior in requests and sessions

Requests and session continuations must be allowed to attach skill references directly:

```python
session = "some prompt" @ my_skill_obj >> agent
"another prompt" @ skills("some-skill") >> session
```

The required behavior is:

- Request- or session-attached skills are references to skills already loaded into the target agent/session.
- If the referenced skill is already loaded, pyflow must render prompt guidance instructing the agent to use that skill.
- If the referenced skill is not loaded into the target agent/session, pyflow must raise an error instead of silently adding prompt-only guidance.
- A continued `Session` must use the skill catalog that was present when its underlying OpenHands agent was created. Request/session attachments must not implicitly add newly loaded skills to an already-running session.

#### Tool attachment behavior must align with skill attachment behavior

Tool attachments in requests and sessions must follow the same availability rule as skills. Today a request can attach a `Tool` object and pyflow renders a prompt hint even if that tool is absent from the runtime agent. After this task:

- If a request/session attaches a tool reference that is already loaded into the target agent/session, pyflow must render the existing prompt guidance for using that tool.
- If the tool is not loaded into the target agent/session, pyflow must raise an error.
- Request/session attachment of a tool must no longer act as a prompt-only escape hatch for unavailable tools.
- Agent-level tool registration remains the place where runtime tool availability is established.

#### Skill source handling

The public `skills(...)` entry point must support all of the following user-visible cases:

```python
from pathlib import Path
from openhands.sdk.context import Skill

my_skill_obj: Skill = ...

skills(my_skill_obj)
skills(Path("path/to/skill-folder"))
skills("path/to/skill-folder")
skills(".")
skills("some-skill")
```

The required behavior is:

- Existing OpenHands `Skill` instances are accepted directly.
- Path-like inputs may be used to make skills available on an agent by loading them from filesystem-backed OpenHands skill locations.
- Name-based references such as `"some-skill"` are valid in request/session attachments only when that skill is already available in the target agent/session.
- The framework must not invent a parallel pyflow skill object model at this stage.

#### Error behavior

The new errors must be early, explicit, and deterministic. In particular:

- Starting from a request or session attachment site is acceptable as long as the failure clearly explains that the referenced skill/tool is not loaded into the target agent/session.
- The framework must not degrade to best-effort prompt rendering when resolution fails.
- The framework must not silently register new skills or tools during session continuation.

#### Notes

- This task must use the OpenHands SDK `Skill` class directly rather than introducing a pyflow-defined replacement.
- The public `skills(...)` signature must inline accepted value types in the annotation and must not introduce a `SkillInput` alias.
- `SkillSet` is the pyflow attachment/container abstraction; it is not a replacement for the OpenHands SDK `Skill`.
- The current OpenHands integration in [pyflow/agent.py](pyflow/agent.py) builds an SDK `Agent` with tools only. Completing this task will require a substantial change to that adapter because skills are supplied through OpenHands `AgentContext`, not through the existing prompt-only `Context` rendering path.
- The current tool behavior in [tests/test_tools.py](tests/test_tools.py) explicitly treats request-attached tools as prompt-only. That current behavior is part of the problem statement and must change as part of this task.

### Review notes

1. Tightened the scope so the task is specifically about OpenHands skill integration plus the matching request/session resolution rules for skills and tools, without expanding into installed-skill lifecycle features.
2. Made the distinction between current behavior and desired behavior explicit, especially the fact that request-attached tools are currently prompt-only and that `Agent` does not yet support `@` composition.
3. Incorporated the user constraints directly into the spec: no pyflow `Skill` class, `SkillSet` is acceptable, and the `skills(...)` public annotation must inline `str | Path | Skill` instead of introducing `SkillInput`.
4. Clarified that request/session skill and tool attachments are references against already-loaded runtime state, not a mechanism for late registration, and that failure must raise an error instead of silently rendering hints.
5. Added concrete DSL examples for agent attachment, request attachment, and session continuation so the desired semantics are unambiguous before implementation planning begins.

## Implementation

### 1. Add a dedicated skill attachment layer that stays on top of the OpenHands SDK `Skill`

The implementation must introduce a pyflow container for skill attachments, but it must not introduce a second skill model parallel to OpenHands `Skill`. The pyflow object exists only to fit the existing attachment DSL and to defer resolution until pyflow knows whether the attachment is being used for agent loading or request/session referencing.

#### 1.1 Create `pyflow/skills.py`

Add a new focused module that owns all skill-related pyflow behavior.

This module must define:

- `SkillSet` as a frozen attachable object.
- `skills(*values: str | Path | Skill) -> SkillSet` with the value annotation inlined exactly in the public signature.
- Internal helper functions for:
  - normalizing the raw inputs into an immutable tuple
  - rendering skill guidance text from reference names
  - resolving agent-scoped skill inputs into concrete OpenHands `Skill` instances
  - extracting referenced skill names from request/session attachments
  - validating referenced skill names against an available skill catalog

`SkillSet` should inherit from [pyflow/context.py](pyflow/context.py) `Context` instead of adding a new attachment base type. That choice keeps `Step.attachments` and `Request @ attachment` unchanged, because tools already fit the existing `Context`-based attachment storage and `SkillSet` can do the same.

The `SkillSet.render()` behavior should be intentionally narrow:

- It should render prompt guidance such as `Use skill: ...` or `Use skills: ...`.
- It should render by resolved reference names only, not by loading paths.
- It should not try to load files during rendering.

That separation is important because `request.render()` must remain a pure formatting operation. Runtime validation and runtime loading belong elsewhere.

#### 1.2 Define explicit skill resolution rules in `pyflow/skills.py`

Agent-scoped `skills(...)` attachments must support the accepted input forms using deterministic rules. Implement these rules in one internal resolver so the behavior is shared by `Agent.run()` and any future inspection helpers.

Recommended resolution order for each input:

```python
if isinstance(value, Skill):
    return [value]

path = Path(value)

if path.exists() and path.is_file():
    return [Skill.load(path)]

if path.exists() and path.is_dir() and (path / "SKILL.md").exists():
    return [Skill.load(path / "SKILL.md")]

if path.exists() and path.is_dir() and path.name in (".agents", ".claude"):
    return flatten(load_skills_from_dir(path / "skills"))

if path.exists() and path.is_dir() and path.name in ("skills", "microagents"):
    return flatten(load_skills_from_dir(path))

if path.exists() and path.is_dir():
    return load_project_skills(path)

return reference_name(value)
```

The important semantic split is:

- Agent attachment may load from paths and directories.
- Request/session attachment is reference-only.

That means path-backed inputs attached directly to a request or session should fail with a clear error explaining that path-based skill loading is only supported when attaching to an `Agent`. Name-based references and direct `Skill` instances remain valid there.

Skill deduplication must happen by skill name after agent-side resolution. To stay aligned with the existing tool compilation model, the last attached skill with a given name should win.

#### 1.3 Add operator support for raw OpenHands `Skill` objects without creating a pyflow `Skill` subclass

The syntax `"some prompt" @ my_skill_obj` cannot work with the SDK `Skill` class as-is, because Python falls back to the right-hand operand’s `__rmatmul__`, and OpenHands `Skill` does not implement that operator.

To satisfy the required syntax without introducing a pyflow-defined `Skill` subclass, `pyflow/skills.py` must install a small compatibility shim onto the imported OpenHands `Skill` class at import time:

```python
def _skill_rmatmul(self: Skill, payload: StepInput) -> Step:
    return skills(self).__rmatmul__(payload)
```

Implementation notes:

- The shim must be installed idempotently.
- The shim should delegate immediately to `skills(self)` so pyflow still stores a `SkillSet` attachment, not a raw SDK `Skill` object.
- The shim must live in the skill module and be imported as part of normal pyflow package import so users do not need extra setup before using `"prompt" @ my_skill_obj`.

### 2. Teach `Agent` to own agent-scoped skill and tool attachments

The current agent adapter in [pyflow/agent.py](pyflow/agent.py) owns global prompt contexts and runtime tools, but it has no skill state and no `@` composition support. This task must make `Agent` the runtime capability owner for both tools and skills.

#### 2.1 Extend `pyflow/agent.py` with attachment-aware immutable composition

Add `Agent.__matmul__` and implement explicit attachment dispatch. The dispatch order matters:

1. `SkillSet`
2. `Tool`
3. generic `Context`

`Tool` must be checked before generic `Context` because pyflow tools are already `Context` subclasses. `Agent.__imatmul__` does not need a custom implementation; normal Python augmented assignment can reuse `__matmul__` because `Agent` is immutable.

The method should return a new `Agent` value with the attachment added to the correct agent-scoped storage:

- skill attachments become part of the agent’s runtime skill inputs
- tool attachments become part of the agent’s runtime tool list
- other contexts continue to populate the agent’s global prompt preamble

Do not route `SkillSet` through the existing `contexts` field. Skill availability is runtime state, not free-form prompt text.

#### 2.2 Add an internal agent capability resolution step in `pyflow/agent.py`

`Agent.run()` currently builds an OpenHands agent and starts a conversation in one pass. This task needs a richer intermediate representation, because pyflow must know:

- the compiled OpenHands tool specs
- the resolved OpenHands `Skill` list
- the names of tools available to runtime validation
- the names of skills available to runtime validation
- the `AgentContext` object passed into the SDK agent

Introduce a private helper in `pyflow/agent.py` that resolves agent-scoped attachments into a single runtime snapshot before the `Conversation` is created. This may be a private frozen dataclass or a small private tuple-returning helper; the exact internal shape is not public API.

That helper must:

- flatten and compile tools using existing `pyflow.tooling` helpers
- resolve and deduplicate skills through the new `pyflow.skills` helpers
- build `AgentContext(skills=resolved_skills)`
- keep global prompt contexts separate from the OpenHands skill list
- produce stable `tool_name` and `skill_name` catalogs for validation

#### 2.3 Build the SDK `Agent` with `agent_context`

Update the OpenHands build path in [pyflow/agent.py](pyflow/agent.py) so `_build_openhands_agent()` (or its replacement helper) passes the resolved skill catalog into:

```python
OpenHandsAgent(
    llm=self.model.build_llm(),
    tools=list(tool_specs),
    agent_context=agent_context,
    system_prompt_kwargs={"cli_mode": True},
)
```

The current global context preamble behavior should stay intact for this task. Agent-level `contexts=` already have tests and existing semantics; the skill work should not silently redefine them. The implementation should therefore add `agent_context` for skills while preserving the existing `_render_message()` preamble logic for non-skill contexts.

### 3. Make request and session attachment execution runtime-aware

Strict loaded-capability checking must happen at execution time, not at standalone render time. A `Request` by itself does not know which agent or session it will target, so `Request.render()` and `Step.render()` should stay generic string renderers.

#### 3.1 Add runtime validation before `conversation.send_message(...)`

Add a private validation pass in [pyflow/agent.py](pyflow/agent.py) that runs immediately before sending a rendered request to OpenHands.

That pass must:

- walk every step attachment in the request
- collect referenced tool names from `Tool` / `ToolSet` attachments
- collect referenced skill names from `SkillSet` attachments
- ignore generic non-runtime `Context` attachments such as `docs(...)` and `code(...)`
- compare requested tool names against the runtime tool-name catalog
- compare requested skill names against the runtime skill-name catalog

If all referenced runtime capabilities are present, pyflow should continue to send the usual rendered request text. If anything is missing, pyflow must raise an error before `conversation.send_message(...)`.

The validation error messages should include:

- what kind of capability is missing (`tool` or `skill`)
- the missing names
- the available names in the target runtime
- whether the target was a fresh agent run or a continued session

#### 3.2 Align tool behavior with the new skill behavior

Today tool handling has two different layers:

- `tools("unknown-name")` fails early because name lookup happens against the pyflow tool registry.
- request-attached tool objects still render prompt text even if the target agent did not load them.

After this task, keep the first layer unchanged and add the second layer:

- registry lookup still happens at `tools(...)` construction time
- runtime availability lookup must happen again when executing a request or session continuation

This is the behavior needed to make tools and skills consistent. A tool can be structurally valid in pyflow yet still unavailable in a given runtime; that second failure must become explicit.

`pyflow/tooling.py` should gain small internal helpers for extracting flattened tool names from tool attachments so `Agent` does not need to know `ToolSet` internals.

#### 3.3 Capture runtime capability catalogs on `Session`

`Session.__rrshift__` must validate continuation attachments against the exact capabilities that were loaded when the session started. Relying on the current `Agent` object alone is not sufficient, because:

- a session may outlive later reassignment of the original agent variable
- tests sometimes construct `Session(...)` directly
- pyflow should not rely on undocumented OpenHands agent internals to recover skill catalogs from the backend object

Update [pyflow/session.py](pyflow/session.py) so `Session` stores private capability snapshots populated at creation time, for example:

- available tool names
- available skill names

These private fields should have safe defaults so existing direct `Session(...)` test fixtures do not all need immediate rewrites. When defaults are used, continuation validation may fall back to the attached pyflow `Agent`’s current resolved catalogs.

The continuation path in `Session.__rrshift__` should then call the same validation helper used by fresh runs before invoking `conversation.run()`.

### 4. Keep request/step storage stable and export the new skill surface

The request DSL should not be refactored more than necessary. The cleanest implementation is to make skills fit the existing attachment model rather than redesigning the attachment model around skills.

#### 4.1 Leave `pyflow/request.py` and `pyflow/steps.py` structurally unchanged

Because `SkillSet` is a `Context`, step and request attachment storage can remain as:

- `Step.attachments: Sequence[Context]`
- `Request.__matmul__(attachment: Context)`

That keeps current operator precedence and rendering tests mostly intact. The important new behavior is introduced in execution-time validation, not by redesigning the request object graph.

No change is needed to standalone `Request.render()` semantics beyond whatever skill prompt string `SkillSet.render()` contributes.

#### 4.2 Export the new skill API and ensure the operator shim is installed

Update [pyflow/__init__.py](pyflow/__init__.py) to export:

- `SkillSet`
- `skills`

Import ordering must ensure that `pyflow/skills.py` is imported during normal pyflow package import so the OpenHands `Skill.__rmatmul__` shim is installed before user code attempts `"prompt" @ my_skill_obj`.

### Review notes

1. Reworked the implementation around a dedicated `pyflow/skills.py` module so the plan clearly separates three concerns: DSL attachment shape, agent-side loading, and runtime validation.
2. Added the explicit operator-shim step for raw OpenHands `Skill` objects because the desired `"prompt" @ my_skill_obj` syntax is otherwise impossible without introducing a pyflow `Skill` subclass.
3. Clarified that `Request.render()` must remain pure and generic, and moved all loaded-capability checks into the fresh-run and session-continuation execution paths.
4. Added a concrete agent runtime-resolution stage so the plan explains how skills, tools, `AgentContext`, and validation catalogs are produced together rather than scattered across `run()` and `Session`.
5. Tightened the session-continuation part by requiring private capability snapshots with safe defaults, which preserves existing manual `Session(...)` construction sites while still enforcing the new semantics during real runs.

## Testing

Assumption for this testing plan: cover the feature with local deterministic tests only. Do not add tests that depend on the network, the public OpenHands extensions repository, or live provider-backed LLM execution.

### `tests/test_skills.py`

Add a new focused test module for the new skill DSL surface and agent-side skill resolution. This module should own the pure skill API cases so runtime tests can stay focused on execution behavior.

Test cases to add:

- `skills(...)` returns a `SkillSet` for:
  - an SDK `Skill` instance
  - a `Path`
  - a `str`
- `SkillSet` is immutable and preserves the original value ordering.
- `SkillSet.render()` uses singular wording for one skill and plural wording for multiple skills.
- `SkillSet.render()` renders reference names only and does not leak raw loading-path text into the prompt when agent-side inputs came from directories.
- importing pyflow installs the OpenHands `Skill.__rmatmul__` compatibility shim, so `"some prompt" @ my_skill_obj` produces a step whose attachment is a `SkillSet`.
- `skills(my_skill_obj)` attached to a step round-trips through `Request.render()` as skill guidance text.
- agent-side resolution loads a single skill from a directory containing `SKILL.md`.
- agent-side resolution loads skills from a project root by discovering `.agents/skills/`.
- agent-side resolution accepts an already-constructed SDK `Skill` instance without reloading from disk.
- duplicate loaded skill names are deduplicated by name with last-one-wins behavior.
- request/session-side path-backed `SkillSet` inputs are rejected with a clear error stating that path-based loading is only allowed on `Agent`.
- request/session-side name references remain valid as references and do not try to touch the filesystem.

Non-trivial supporting test changes:

- Add local helper functions at the bottom of the module to create temporary `SKILL.md` directories and, where needed, minimal project roots with `.agents/skills/<skill-name>/SKILL.md`.
- Use temporary directories rather than committed fixtures so each case can control exact skill names and duplicate-name scenarios.
- Use direct SDK `Skill(...)` construction for the in-memory cases instead of loading every test skill from disk.

### `tests/test_runtime.py`

Extend runtime tests to verify that agent skill loading, request/session validation, and continuation semantics work with the existing `TestModel` flow.

Test cases to add:

- `Agent @ skills(...)` returns a new immutable agent value and leaves the original agent unchanged.
- `Agent @ tools(...)` still returns a new immutable agent value and can be chained with `Agent @ skills(...)`.
- a fresh run from an agent with loaded skills builds an OpenHands agent whose `agent_context.skills` contains the resolved skills.
- agent-level non-skill contexts still render into the message preamble while loaded skills go into `agent_context`, proving that skills did not get incorrectly folded into the old prompt-only context path.
- a request that attaches a loaded SDK `Skill` instance runs successfully and sends prompt text that tells the agent to use the skill.
- a request that attaches `skills("loaded-skill-name")` runs successfully when that skill is present in the agent runtime catalog.
- a request that attaches an unloaded skill name raises before `conversation.send_message(...)` or `conversation.run()` is reached.
- a request that attaches an unloaded SDK `Skill` object raises if the skill name is not part of the agent runtime catalog.
- a session continuation with `skills("loaded-skill-name")` succeeds when that skill was part of the original session capability snapshot.
- a session continuation with an unloaded skill name raises and does not call `conversation.run()`.
- session continuation validation uses the session capability snapshot rather than any later mutation/rebinding of the original agent variable.
- a directly constructed `Session(...)` with no explicit snapshot still has a safe fallback path for continuation validation, so legacy test construction does not crash on missing private fields.

Non-trivial supporting test changes:

- Add or extend a lightweight fake/capture conversation to assert that failing validation happens before any outbound message is sent.
- Add assertions against the built OpenHands agent object to inspect `agent_context.skills` rather than inferring skill loading only from rendered prompt text.
- Where needed, create temporary skill directories inside the runtime test itself rather than sharing filesystem fixtures across modules.

### `tests/test_tools.py`

Update tool tests so tools follow the same loaded-capability rule as skills. This file already owns most of the tool semantics and should continue to do so.

Test cases to add or update:

- keep the early unknown-name registry failure for `tools("definitely_unknown_tool_test")`; this behavior remains valid and should stay tested.
- replace the current prompt-only continuation test with a stricter test proving that request-attached tools do not get silently registered during session continuation.
- add a fresh-run test where a request attaches a tool that is already loaded into the agent and execution succeeds.
- add a fresh-run test where a request attaches a structurally valid pyflow tool that is not loaded into the agent and validation raises before execution.
- add a session-continuation test where an attached tool that is not in the session capability snapshot raises before execution.
- add a session-continuation test where an attached tool that is in the session capability snapshot succeeds.
- preserve the existing test that agent runtime registration is determined by agent-level tools only, but update the assertions and comments to reflect that request attachments are now validated references rather than prompt-only hints.

Non-trivial supporting test changes:

- Replace assertions that only inspect rendered request text with assertions that also inspect whether execution was allowed or blocked.
- Update any helper names or comments that currently encode the “prompt-only” assumption so the test suite describes the new behavior accurately.

### `tests/test_request_dsl.py`

Keep DSL/operator tests narrow and syntax-focused. Only add cases here that are about operator behavior rather than runtime loading.

Test cases to add:

- `"prompt" @ skills("named-skill")` produces a prompt step with one attachment.
- operator precedence for `>>` and `@` remains correct when the right-hand attachment is `skills(...)`.
- request immutability is preserved when attaching a `SkillSet`.

These tests must stay render/structure-focused and should not duplicate runtime validation already covered elsewhere.

### Review notes

1. Split the testing surface into a new dedicated `tests/test_skills.py` plus targeted updates to runtime and tool tests, so each module has a single reason to change.
2. Chose local temporary skill directories over committed skill fixtures because duplicate-name, project-root, and single-folder cases are easier to control and less brittle that way.
3. Kept `tests/test_request_dsl.py` intentionally small to avoid mixing syntax/operator coverage with runtime validation, which belongs in runtime-oriented modules.
4. Added explicit coverage for the hardest behavioral edge: request/session attachments must validate against loaded runtime catalogs and must fail before any message send or conversation run occurs.
5. Recorded the key testing assumption up front: no network-backed public skill loading or live provider execution belongs in this task’s test scope.
