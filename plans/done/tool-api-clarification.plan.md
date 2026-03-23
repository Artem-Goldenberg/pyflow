# Clarify the Tool API by Separating Definition from Lookup

## Summary

Pyflow already has a working typed tool layer, but the current public name `tool` is overloaded: it defines function-backed tools, looks up registered tools by name, and exposes grouped tool composition through `.use(...)`. That overlap becomes harder to understand once definition-only annotation flags are part of the public surface.

This task clarifies the public API by making `tool` definition-only and introducing a new public `tools(...)` entry point for lookup and grouping. After implementation, testing must confirm the new public calling forms, rejection of the old mixed-use forms, correct scoping of definition-only flags, and preservation of existing tool attachment and runtime execution behavior.

## Introduction

### Prerequisites

- **Documentation**
  - `ARCHITECTURE.md`
    - `Component Map`, especially `Tool Layer (`pyflow.tooling`)`
    - `Design Principles`
    - `Data Flow`
    This document matters because it describes the tool layer as a user-facing DSL surface that should stay typed and explicit.
  - `AGENTS.md`
    - `Conventions`
    - `Import Style`
    - `Testing`
    - `Near-Term Priorities`
    This document matters because it defines the project’s API and typing expectations, including the requirement to ask before making ambiguous API decisions.
  - `IMPLEMENTATION_PLAN.md`
    - `Phase 2: Tool Abstraction Layer`
    This file matters because it confirms that the tool API is still being actively shaped and is part of the core abstraction work.

- **Related code**
  - `pyflow/tooling.py` — current public tool API, registration path, `FunctionTool`, `ToolSet`, lookup logic, and OpenHands compilation boundary
  - `pyflow/__init__.py` — current public exports for the tool API
  - `tests/test_tools.py` — current public-behavior and regression coverage for decorator usage, lookup, grouping, and execution
  - `pyflow/agent.py` — runtime compilation path that must keep working after the public API split

### Problem

Currently, pyflow already provides the core tool abstractions we want: `FunctionTool` wraps local Python tools, wrapped OpenHands tools can be imported, `ToolSet` groups tools immutably, and the runtime compiles attached tools into OpenHands-visible specs.

But the current public surface mixes several different concepts behind one name. In `pyflow.tooling`, the public `tool` object currently supports all of the following:

- `@tool` and `@tool(name="...")` for definition
- `tool("existing_name")` for lookup
- `tool.use(...)` for grouping and flattening
- definition-only kwargs such as `read_only=...`, `destructive=...`, `idempotent=...`, and `open_world=...`

This creates an API boundary that is difficult to explain and easy to misuse. A user can see one public callable that appears to both define and resolve tools, and the implementation is forced to distinguish omitted definition kwargs from lookup calls. That confusion is exactly the opposite of the intended API meaning: definition-time options should belong only to tool definition, and lookup should be a separate concept with its own name.

This task solves the problem by splitting the public surface into two explicit roles:

- `tool` defines function-backed tools
- `tools(...)` resolves already-defined tools and groups them when needed

### Task

This task belongs to the public tool API. It is not a redesign of `FunctionTool`, `ToolSet`, OpenHands compilation, or runtime execution semantics. The task is to make the public meaning of tool-related names obvious from their spelling and to remove the current overlap between definition and lookup.

The required behavior is:

- `tool` must be a definition-only public API
- `tools(...)` must be the public API for resolving previously registered tools by name and for forming grouped tool attachments when more than one tool is requested
- definition-only kwargs such as `read_only`, `destructive`, `idempotent`, and `open_world` must be accepted only on definition APIs, not on lookup APIs
- the public API must no longer encourage or require a user to remember that one callable means “definition” in one form and “lookup” in another

The scope of this task is exactly the following:

- clarify the public meaning of `tool`
- add the new public lookup/grouping name `tools`
- move user-facing lookup away from `tool("name")`
- move user-facing grouped lookup away from `tool.use(...)`
- keep existing tool objects, `ToolSet`, and runtime tool execution behavior working after the public split

The scope explicitly excludes:

- changing `FunctionTool.from_openhands(...)`
- changing OpenHands tool execution behavior
- changing request attachment syntax (`@`) or sequencing syntax (`>>`)
- changing how built-in wrapped tools such as `terminal_tool`, `read_file_tool`, and `apply_patch_tool` execute at runtime

The completion of this task must produce the following user-facing changes.

#### 1. `tool` becomes definition-only

Current public usage mixes definition and lookup:

```python
from pyflow import tool

@tool(name="my_tool")
def my_tool(value: str) -> str:
    """Example."""
    return value

same_tool = tool("my_tool")
```

After this task, `tool` must mean “define a local Python tool”, not “look up a tool”.

Illustrative examples:

```python
from pyflow import tool

@tool
def my_tool(value: str) -> str:
    """Example."""
    return value

@tool(name="custom_tool", read_only=True, open_world=False)
def custom_tool(value: str) -> str:
    """Example."""
    return value
```

Expected behavior:

- `@tool` remains valid
- `@tool(...)` remains valid for definition-time options such as `name=...` and the annotation flags
- definition-time flags remain allowed on other definition surfaces that create a new local tool, specifically `FunctionTool.from_function(...)`
- `tool("existing_name")` is no longer a valid public lookup form
- `tool.use(...)` is no longer a valid public grouping form

#### 2. A new public API named `tools(...)` handles lookup and grouping

This task introduces one new public API name:

- `tools`

`tools(...)` must be the user-facing way to resolve already-registered tools when the user needs them by name, especially inside request attachments.

Illustrative examples:

```python
from pyflow import tools

step = "Inspect the file." @ tools("read_file")
step = "Make the edit." @ tools("read_file", "apply_patch")
```

Expected behavior:

- `tools("read_file")` returns the already-registered tool object for that name
- `tools("read_file", "apply_patch")` returns an attachable grouped tool value equivalent in user-facing behavior to the current multi-tool composition path
- the grouped result must preserve the current rendered prompt behavior and OpenHands compilation behavior for multiple attached tools
- `tools(...)` is a lookup/grouping surface, not a definition surface
- `tools()` with no tool arguments is invalid

#### 3. Definition-only flags are not part of the lookup API

Current confusion comes from the fact that the same public callable is trying to represent both definition and lookup.

After this task, the public rule must be simple:

- definition flags belong only to tool definition
- lookup/grouping does not accept them

Illustrative examples:

```python
from pyflow import FunctionTool, tool, tools

@tool(read_only=True, open_world=False)
def read_project_file(path: str) -> str:
    """Read a file."""
    return path

wrapped = FunctionTool.from_function(
    read_project_file,
    name="read_project_file_copy",
    read_only=True,
    open_world=False,
)

attached = "Review this file." @ tools("read_project_file")
```

Expected behavior:

- `@tool(read_only=True, ...)` is valid because it defines a tool
- `FunctionTool.from_function(..., read_only=True, ...)` is valid because it defines a tool
- `tools("read_project_file", read_only=True)` is invalid because `tools(...)` is not a definition API
- a user must never need to reason about “omitted vs explicitly false” lookup kwargs to use the public API correctly

#### 4. Existing attachment and runtime behavior stays semantically the same

This task is about public naming clarity, not runtime semantics.

Illustrative examples:

```python
from pyflow import tool, tools

@tool
def summarize_issue(text: str) -> str:
    """Summarize an issue."""
    return text.upper()

step = "Summarize this issue." @ summarize_issue
step_by_name = "Summarize this issue." @ tools("summarize_issue")
multi = "Prepare the change." @ tools("read_file", "apply_patch")
```

Expected behavior:

- attaching a directly defined tool object still works
- attaching a looked-up tool by name still works, but now uses `tools(...)`
- attaching multiple tools still works, but now uses `tools(...)`
- tool rendering and runtime compilation keep the same semantics they have today for equivalent tool attachments

#### Notes

- New public API names introduced by this task:
  - `tools`
- Existing public API names whose meaning changes:
  - `tool` becomes definition-only
- Existing public forms that this task retires from the public API:
  - `tool("name")`
  - `tool.use(...)`
- This task is about clarity of the public contract. Whether the implementation temporarily keeps a compatibility shim internally is not part of the task specification; the public API after this task must clearly direct users to `tool` for definition and `tools(...)` for lookup/grouping.

### Review notes

1. **Pass 1:** Framed the task around current public behavior in `pyflow.tooling` rather than around the `_UNSET` implementation detail, because the real problem is the overloaded user-facing meaning of `tool`.
2. **Pass 2:** Made the split unambiguous by explicitly listing the new public API name `tools`, the changed meaning of `tool`, and the retired forms `tool("name")` and `tool.use(...)`.
3. **Pass 3:** Added the rule that definition-only flags remain valid on definition APIs, including `FunctionTool.from_function(...)`, while lookup/grouping rejects them completely.
4. **Pass 4:** Clarified that this task preserves attachment and runtime semantics, so the API clarification is isolated to naming and public entry points rather than changing OpenHands integration behavior.

## Implementation

The implementation should be split into four goals.

### Goal 1. Make `tool` a definition-only public surface

This goal removes the current public overlap between definition and lookup.

#### File: `pyflow/tooling.py`

- Reshape the current `_ToolFactory` so that its public responsibility is only local-tool definition.
- Keep support for the two definition forms that matter to users:

```python
@tool
def foo(...) -> ...:
    ...

@tool(name="foo", read_only=True, ...)
def foo(...) -> ...:
    ...
```

- Keep the corresponding callable definition path for already-existing Python callables, because `@tool` desugars through that same code path:

```python
tool(function, name="foo", read_only=True, ...)
```

- Remove the string-lookup branch from `tool.__call__`.
- Remove the public `.use(...)` method from the `tool` object.
- Simplify `tool.__call__` overloads and implementation accordingly:
  - accepted inputs: a callable to define, or no positional argument when building a decorator
  - rejected inputs: strings and lookup/grouping-style calls
- Delete the implementation detail that only exists to distinguish lookup from definition in one callable:
  - `_UNSET`
  - `_tool_kwarg_or_default(...)`
- Replace the current error text with definition-only guidance, for example wording of the shape “Use `@tool` or `@tool(...)` to define a tool.”
- Preserve the existing registration path through `FunctionTool.from_function(...)`; this task clarifies public entry points and must not fork local-tool registration logic into a second code path.

#### File: `pyflow/tooling.py` docstrings

- Update the `_ToolFactory` docstring so it documents only definition behavior.
- Remove references to `tool("existing_name")` and `tool.use(...)`.
- Keep the definition-only annotation kwargs documented on the decorator surface.

### Goal 2. Add `tools(...)` as the lookup and grouping API

This goal replaces both `tool("name")` and `tool.use(...)` with one explicit public name.

#### File: `pyflow/tooling.py`

- Add a new public helper named `tools`.
- Implement it as a narrow lookup/grouping entry point, preferably a plain function, because unlike `tool` it does not need decorator behavior.
- Reuse the existing helper flow already present in the module:
  - `_convert_tool(...)`
  - `_resolve_registered_tool(...)`
  - `ToolSet(...)`
- Make the function variadic so it replaces both current lookup and grouping flows:

```python
def tools(*values: Tool | str) -> Tool:
    ...
```

- Preserve current grouping power by accepting the same logical inputs that `tool.use(...)` accepts today:
  - a registered tool name
  - a concrete `Tool` instance
- Define the return contract explicitly:
  - one resolved value returns that single `Tool`
  - multiple resolved values return `ToolSet(tools=...)`
- Reject zero-argument calls with a clear lookup-oriented error.
- Do not accept definition kwargs on `tools(...)`; the signature itself should make this impossible rather than relying on late validation.
- Keep name resolution and duplicate-name behavior unchanged after resolution. In particular, the runtime compile boundary should still rely on `flatten_tools(...)` and `compile_openhands_tools(...)` exactly as it does today.

#### File: `pyflow/tooling.py` supporting text and helpers

- Update module docstrings and inline comments so `tools(...)` is described as a lookup/grouping surface, not a definition surface.
- Keep `_convert_tool(...)` as the single place that normalizes `Tool | str` inputs.
- Keep `_resolve_registered_tool(...)` error wording aligned with the new public names, so failures mention `tool` for definition and `tools(...)` for lookup.

### Goal 3. Update public exports and internal call sites

This goal makes the new split visible from `pyflow` and removes old public-form examples from the repository.

#### File: `pyflow/__init__.py`

- Export `tools` alongside `tool`.
- Add `tools` to `__all__`.
- Keep the rest of the tool-layer exports unchanged.

#### File: `tests/test_tools.py`

- Replace repository-internal uses of the old lookup form:
  - `tool("name")` -> `tools("name")`
- Replace repository-internal uses of the old grouping form:
  - `tool.use(...)` -> `tools(...)`
- Update imports accordingly.

#### File: `pyflow/tooling.py` public messaging

- Update any user-facing TypeError or ValueError messages so they point to the new split:
  - definition guidance mentions `@tool` / `@tool(...)`
  - lookup guidance mentions `tools(...)`
- Remove stale wording that suggests one public callable still handles both roles.

### Goal 4. Preserve behavior while tightening the API boundary

This goal ensures the split is an API clarification rather than a behavioral rewrite.

#### File: `pyflow/tooling.py`

- Leave `FunctionTool`, `ToolSet`, `flatten_tools(...)`, `compile_openhands_tools(...)`, and the OpenHands executor/definition wiring semantically unchanged unless a change is strictly required to support the new public surface.
- Keep definition-only flags on `FunctionTool.from_function(...)`.
- Keep `ToolContext` handling unchanged.
- Keep built-in OpenHands wrappers (`terminal_tool`, `read_file_tool`, `apply_patch_tool`) unchanged.
- Keep duplicate-registration behavior unchanged.

#### File: `tests/test_tools.py`

- Preserve the existing tests that validate schema mapping, OpenHands execution, duplicate replacement, context injection, and compilation semantics.
- Only rewrite the parts of the suite that currently encode the old public API contract.

### Review notes

1. **Pass 1:** Chose `tools(*values: Tool | str)` as the replacement surface so the new split preserves the practical composition power of `tool.use(...)` instead of narrowing the API to string-only lookup.
2. **Pass 2:** Kept `FunctionTool.from_function(...)` untouched as the single local-tool registration path, because introducing a second implementation path would weaken the clarification effort and create unnecessary drift.
3. **Pass 3:** Moved error-message updates into their own implementation goal details so the public contract is clarified not only by signatures, but also by failure modes.
4. **Pass 4:** Rechecked the file list against the current repository and kept the implementation localized to `pyflow/tooling.py`, `pyflow/__init__.py`, and `tests/test_tools.py`, with no runtime-layer changes planned.

## Testing

Testing for this task belongs entirely in `tests/test_tools.py`, because the change is a public tool-API clarification with no intended runtime behavior change outside the tool layer. No compatibility coverage should be added for the retired public forms: `tool("name")` and `tool.use(...)` must be treated as invalid immediately.

### File: `tests/test_tools.py`

Add or rewrite tests to cover the following cases.

- **Definition-only decorator path still works**
  Verify that `@tool` still registers a function-backed tool using the function name, and that `@tool(name="...")` still registers with an explicit name.

- **Definition-only annotation kwargs remain accepted on `tool`**
  Verify that `@tool(read_only=..., destructive=..., idempotent=..., open_world=...)` still succeeds and still maps to the expected `ToolAnnotations` on the registered OpenHands definition.

- **Definition-only annotation kwargs remain accepted on `FunctionTool.from_function(...)`**
  Verify that `FunctionTool.from_function(..., read_only=..., ...)` still succeeds and still maps to the expected `ToolAnnotations`.

- **`tools("name")` resolves a registered local tool**
  Replace the current lookup test that uses `tool("count_letters_tool_test")` with a `tools("count_letters_tool_test")` assertion and verify that it returns the same registered `FunctionTool` object.

- **`tools("name")` resolves a wrapped OpenHands tool**
  Replace the current lookup test that uses `tool("read_file")` with `tools("read_file")` and verify that the built-in wrapped tool is returned.

- **`tools(...)` groups multiple tools**
  Replace the current `tool.use(...)` grouping test with `tools(...)`.
  Verify:
  - one name returns a single `Tool`
  - multiple names return a `ToolSet`
  - nested composition cases that previously relied on `tool.use(...)` are either no longer needed or are rewritten in terms of direct `ToolSet` construction only if such a helper is still part of the public surface after implementation
  - rendered prompt text stays the same for equivalent grouped inputs

- **Request attachment by name uses `tools(...)`**
  Rewrite attachment tests so `"Fix this." @ tools("attachment_lookup_tool_test")` works and attaches the resolved tool object.

- **Multi-tool request attachments use `tools(...)`**
  Rewrite request-rendering coverage that currently attaches `tool("merge_request_tool_test")` so it uses `tools("merge_request_tool_test")`, and keep the assertions about rendered tool instructions and runtime agent tool registration.

- **Unknown-name lookup still fails early through `tools(...)`**
  Replace the current `tool("definitely_unknown_tool_test")` failure test with `tools("definitely_unknown_tool_test")` and keep the early-error assertion.

- **`tools()` with no arguments fails**
  Add a new negative test that calling `tools()` raises a clear error, because zero-argument lookup/grouping is invalid in the new API.

- **`tools(...)` does not accept definition kwargs**
  Add a new negative test that calls such as `tools("read_file", read_only=True)` are rejected. This test should assert the actual public contract: lookup/grouping is not a definition API.

- **`tool("name")` is invalid immediately**
  Replace the old lookup-contract tests with a new negative test asserting that `tool("some_name")` now raises a definition-only error.

- **Existing execution and compilation tests remain green after API rewrite**
  Keep the existing tests for:
  - schema generation
  - observation-return handling
  - duplicate replacement
  - OpenHands execution loop integration
  - request-attached-tool prompt-only behavior
  - compile-last-tool-wins behavior
  These tests should be updated only where they currently encode the retired public lookup/grouping forms.

### Non-trivial test-suite adjustments

- Update imports in `tests/test_tools.py` to import `tools` from `pyflow`.
- Rename test functions whose names currently refer to “tool factory supports lookup” or “tool use” so the names describe the new public API instead of historical implementation details.
- Remove assertions that encode backward compatibility for the retired forms; this task explicitly does not preserve them.

### Review notes

1. **Pass 1:** Incorporated your clarification that no backward compatibility is required, so the test plan now requires immediate failure for `tool("name")` and `tool.use(...)` rather than warning-only or dual-path behavior.
2. **Pass 2:** Kept the testing scope in `tests/test_tools.py` because the task changes the public tool API contract, not the runtime/session layer.
3. **Pass 3:** Split the plan between rewrites of existing lookup/grouping tests and genuinely new negative tests, so the implementer can distinguish migration work from new coverage requirements.
4. **Pass 4:** Tightened the grouped-lookup test language to avoid accidentally requiring nested `tools(...)` behavior that the final implementation may not need, while still preserving multi-tool attachment coverage.
