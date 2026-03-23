# Request DSL Core (Immutable, Step + Context)

**Summary**
- Implement immutable `Request` as a tuple of immutable `Step` objects, with step‑level `Context` attachments.
- Only core types now: `PromptStep`, `TestStep`, `docs(...)`, `code(...)`.
- All classes expose a single uniform `render()` method.
- Also update all the architecture and spec files to be aligned with this plan.

**Implementation Changes**
1. **Module layout**
- `pyflow/context.py`: `Context` ABC, `DocsContext`, `CodeContext`, and helpers `docs(*paths)` / `code(*paths)`.
- `pyflow/steps.py`: `Step` ABC, `PromptStep`, `TestStep`, helper `tests(*names)`.
- `pyflow/request.py`: `Request` only.
- `pyflow/__init__.py`: export the public DSL symbols above.
- Delete `examples/pyflow_dsl_preview.py`.

2. **Context interface**
- `Context` is an abstract base class with `render() -> str` and `__str__` delegating to `render()`.
- `Context.__rmatmul__` supports `"prompt" @ docs(...)` by coercing the LHS into a `Step` and returning `step @ self`.
- To avoid duplication, add a private helper `_coerce_step` (explicitly documented as an internal helper for `__rshift__` and `__rmatmul__`).

3. **Step interface**
- `Step` is an abstract frozen dataclass with:
  - `attachments: Sequence[Context]` storing an immutable tuple of Contexts.
  - `render() -> str` abstract, returning the full human‑readable string including attachments.
  - `__matmul__` adds an attachment immutably and returns a new Step.
  - `__rshift__` starts a `Request` from `self` and appends another step.
  - `__rrshift__` allows `"prompt" >> tests("x")` by coercing the LHS into `PromptStep`.

4. **Concrete Steps**
- `PromptStep(text: str, attachments: Sequence[Context] = ())`
- `TestStep(names: Sequence[str], attachments: Sequence[Context] = ())`
- `tests(*names)` returns a `TestStep`.

5. **Request**
- `Request` is a frozen dataclass storing the **non-empty** tuple of `steps: Sequence[Step]`.
- Use the default dataclass `__init__` (no `__post_init__`, no custom init).
- `__rshift__` appends a coerced step and returns a new `Request`.
- `__matmul__` applies a context to the first step.
- `render()` joins step renders in order, each on its own numbered line.

**Rendering Spec (Best‑Practice, Human‑Readable)**
- Contexts are descriptive sentences, not file lists.
- `DocsContext.render()` returns:
  - `Use documentation files: <path1>, <path2>.`
- `CodeContext.render()` returns:
  - `Use code files: <path1>, <path2>.`
- `PromptStep.render()`:
  - Base: `<text>`
  - Attachments (if any) are appended as separate sentences separated by spaces, in attachment order.
  - Example: `Fix the bug. Use documentation files: plan.md. Use code files: app.py.`
- `TestStep.render()`:
  - Base: `Before finishing, ensure tests pass: <name1>, <name2>.`
  - Attachments appended the same way.
- `Request.render()`:
  - Line 1: `1. <step.render()>`
  - Line 2: `2. <step.render()>`
  - etc.
  - Account for the multiline nested inputs

**Test Plan**
- Add `tests/test_request_dsl.py` verifying:
  - Immutable behavior for `Request` and `Step` after `>>` and `@`.
  - `"prompt" @ docs("a")` yields `PromptStep` with one attachment.
  - `"prompt" >> tests("x")` yields two steps.
  - `("prompt" >> tests("x")) @ code("c.py")` attaches to first step.
  - `"prompt" >> tests("x") @ docs("a")` attaches to `TestStep` (operator precedence).
  - Exact `render()` strings per the spec above. Make them easily adjustable though.
      Perhaps the best way is to store rendered test prompts in separate files 
      (and allow for regeneration).

**Assumptions**
- Immutability is by convention: `Request` requires tuple inputs; no runtime coercion.
- No `git`, `remote`, or other extra Step subclasses yet.
- No file content inlining; contexts only reference files in natural language.
