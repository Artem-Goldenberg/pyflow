# Session Representation in REPL and Notebooks

## Summary

Pyflow already wraps OpenHands conversations in `Session` and already has custom display behavior for REPL and notebook environments, but the visible representation is currently split the wrong way. This task separates live interactive rendering from full session inspection so that session-changing expressions show only the new conversation beautifully, while `session` and `print(session)` show the full pretty session including the real system prompt and related prompt context. After implementation, testing must confirm REPL rendering, notebook cell rendering, continuation deltas, full inspection output, prompt-visibility boundaries, and no automatic live rendering for parallel runs.

## Introduction

### Prerequisites

- **Documentation**:
  - [Project instructions](AGENTS.md)
  - [Architecture overview](ARCHITECTURE.md)
  - [Current implementation roadmap](IMPLEMENTATION_PLAN.md)
  - [OpenHands SDK docs](https://docs.openhands.dev/sdk)
- **Related code**:
  - [Session wrapper](pyflow/session.py)
  - [Interactive display helpers](pyflow/display.py)
  - [Plain-text, Rich, and HTML transcript rendering](pyflow/session_rendering.py)
  - [Notebook conversation rendering](pyflow/notebook_visualizer.py)
  - [Agent execution path](pyflow/agent.py)
  - [Display behavior tests](tests/test_display.py)
  - [Session runtime tests](tests/test_runtime.py)
  - [Notebook renderer tests](tests/test_notebook_visualizer.py)
  - [Notebook integration tests](tests/test_notebook_integration.py)

### Problem

Pyflow now successfully executes requests into reusable `Session` values and already distinguishes common CLI, Python REPL, IPython, and Jupyter display environments. But session-changing expressions can still render nothing in interactive use, notebook live output is currently tied to the wrong output model, and explicit `Session` inspection still omits the real OpenHands system prompt because pyflow drops the corresponding event from its own renderers.

This task solves the mismatch by making pyflow expose two intentionally different session views. Live interactive output should optimize for readability of the current exchange only, while explicit inspection should optimize for completeness and must include the prompt-building context that actually drove the run.

### Task

This task belongs to pyflow's interactive execution UX. A single `Session` participates in two user-facing moments: first, while a request is being started or continued in an interactive environment; second, when the user later inspects the session object itself. Those moments serve different purposes and must no longer share one representation.

The current task is to make session-changing expressions in supported interactive environments render a compact live conversation view, and to make explicit session inspection render a full beautiful session view. The compact live view must show only the new exchange created by the current statement or notebook cell. The full view must show the complete session, including the actual OpenHands system prompt and other prompt-related context recorded in the event stream. This task must not broaden into redesigning notebook input controls, parallel-run live streaming, or introducing a raw Python-object dump as the default visible representation.

The completed behavior must produce the following user-facing changes.

#### New public API names

- `Session.render_full`
- `Session.render_full_markdown`
- `Session.render_full_html`

#### Live rendering for session-changing expressions

When the user starts or continues a non-parallel session in an interactive environment, pyflow must immediately render a compact live conversation view for that specific action.

Illustrative examples:

```python
"Hi" >> agent
```

```python
session = "Hi" >> agent
```

```python
"Continue from the previous answer." >> session
```

The required behavior is:

- In a Python REPL or notebook, a session-changing expression must produce visible live output instead of silently rendering nothing.
- The live output must be beautiful and conversation-oriented, not a Python object repr.
- The live output must contain only the exchange produced by the current action. It must not replay the entire prior session.
- Continuing an existing session must therefore show only the newly appended turns and tool activity.
- In a notebook, the live output must appear in the current cell's output area, not only inside an older cell's previously displayed widget.
- The live output must not expose the system prompt, dynamic context, tool inventory, or other prompt-construction internals.
- The live output must not append the current notebook input/composer controls at the end of the conversation.
- `Agent.parallel(...)` must remain excluded from automatic live rendering.

#### Full session inspection

When the user explicitly inspects the `Session`, pyflow must render a full pretty session representation rather than a partial transcript or a default Python object dump.

Illustrative examples:

```python
session
```

```python
print(session)
```

```python
session.render_full()
```

The required behavior is:

- Evaluating `session` in a REPL or notebook must show the full session representation.
- `print(session)` must also show the full session representation in plain-text form.
- The full view must include the complete conversation history, not only the most recent exchange.
- The full view must include the real OpenHands system prompt taken from the recorded event stream.
- If OpenHands recorded dynamic context alongside the system prompt, that dynamic context must also be shown.
- If prompt extensions or other message-level context were injected into the conversation events, the full view must show them as part of the session representation.
- The full view must remain formatted for humans; it must not degrade into an unstructured debug dump.

#### Boundary between the two views

The two session views must be intentionally different and consistently so.

Illustrative example:

```python
session = "Hi" >> agent
"Refine the answer." >> session
session
```

The required behavior is:

- The first two lines above must render compact live updates only for the work done by those lines.
- The final `session` line must render the full session, including the system prompt and full history.
- Users who want to see the whole session after a continuation must be able to do so by explicitly inspecting the session object.
- Users who only want the readable live conversation while work is happening must not be forced to see prompt internals.

#### Notes

- The current compact renderers exposed by `Session.render()`, `Session.render_markdown()`, and `Session.render_html()` should stay compact and conversation-focused rather than silently changing into full prompt dumps.
- The full session view must be derived from the actual OpenHands events, including the OpenHands system-prompt event, rather than from reconstructed or guessed prompt text.
- The task should preserve the distinction between interactive and non-interactive execution; this task is about REPL and notebook behavior, not about making ordinary scripts print sessions automatically.
- The task should remove the automatic notebook live controls for this path rather than redesigning them.
- The default visible representation of `Session` during explicit inspection should be the full pretty session view, not a raw Python-object representation.

### Review notes

1. Tightened the task to one problem area only: session representation in interactive environments, rather than mixing it with unrelated notebook interaction features.
2. Made the current behavior vs desired behavior explicit by naming the existing suppression path, the notebook output mismatch, and the missing `SystemPromptEvent` coverage in pyflow renderers.
3. Split the requirements into two user-facing views, because the user explicitly wants live conversation output to hide system prompts while explicit session inspection must show them.
4. Added concrete examples for `>> agent`, `>> session`, bare `session`, and `print(session)` so the desired behavior is unambiguous before implementation planning begins.
5. Clarified the scope boundaries that matter for implementation review: no automatic live rendering for parallel runs, no notebook input controls in the live path, no raw object dump as the default visible session representation, and no replay of the full prior transcript during continuation updates.
