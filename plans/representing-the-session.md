# Session Representation and Live Rendering

## Summary

Pyflow already wraps OpenHands conversations in `Session`, but the current printing behavior is inconsistent across REPL, Jupyter, and scripts, and it still carries an unnecessary HTML rendering path. This task standardizes session output into compact live rendering plus full inspection rendering, removes HTML handling entirely, and defines exact default and override behavior for REPL, Jupyter, scripts, and parallel runs. After implementation, testing must confirm REPL Rich behavior, Jupyter markdown-plus-widgets live behavior, script behavior with and without TTY output, explicit full inspection rendering, duplicate-suppression for returned sessions, prompt-visibility boundaries, live-rendering settings, and removal of HTML-specific behavior.

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
  - [Current plain-text, Rich, and HTML transcript rendering](pyflow/session_rendering.py)
  - [Notebook conversation rendering](pyflow/notebook_visualizer.py)
  - [Agent execution path](pyflow/agent.py)
  - [Display behavior tests](tests/test_display.py)
  - [Session runtime tests](tests/test_runtime.py)
  - [Notebook renderer tests](tests/test_notebook_visualizer.py)
  - [Notebook integration tests](tests/test_notebook_integration.py)

### Problem

Pyflow now successfully executes requests into reusable `Session` values and already distinguishes common CLI, Python REPL, IPython, and Jupyter display environments. But session-changing expressions can still render nothing or render through the wrong channel, ordinary `python file.py` execution is not specified precisely enough, notebook live output and explicit notebook inspection still share the wrong rendering path, and explicit `Session` inspection still omits the real OpenHands system prompt because pyflow drops the corresponding event from its own renderers.

This task solves the mismatch by making pyflow expose two intentionally different session views, by defining the default live-rendering behavior for each foreground environment, and by deleting the HTML session-rendering branch entirely. Live output should optimize for readability of the current exchange only, while explicit inspection should optimize for completeness and must include the prompt-building context that actually drove the run.

### Task

This task belongs to pyflow's execution UX across foreground environments. A single `Session` participates in two user-facing moments: first, while a request is being started or continued in a live-rendered foreground run; second, when the user later inspects the session object itself. Those moments serve different purposes and must no longer share one representation.

The current task is to make session-changing expressions in supported non-parallel foreground runs render a compact live conversation view, and to make explicit session inspection render a full beautiful session view. The compact live view must show only the new exchange created by the current statement, script step, or notebook cell. The full view must show the complete session, including the actual OpenHands system prompt and other prompt-related context recorded in the event stream. This task must also give users environment-specific live-rendering settings. This task must not broaden into parallel-run live streaming or introducing a raw Python-object dump as the default visible representation.

The completed behavior must produce the following user-facing changes.

#### New public API names

- `Session.render_full`
- `Session.render_full_markdown`
- `LiveRenderingTarget`
- `set_live_rendering`

#### Live rendering for session-changing expressions

When the user starts or continues a non-parallel session in a supported foreground environment, pyflow must immediately render a compact live conversation view for that specific action.

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

- In a Python REPL or terminal IPython session, `"Hi" >> agent` and `"Hi" >> session` must render compact live output through Rich.
- In Jupyter, `"Hi" >> agent` and `"Hi" >> session` must render compact live markdown output in the current cell and the live output must include the existing ipywidgets controls.
- In an ordinary foreground TTY Python program, `"Hi" >> agent` and `"Hi" >> session` must render compact live plain-text output by default, but may use Rich when the active output channel supports it.
- In an ordinary Python program whose stdout is redirected or otherwise not attached to a TTY, automatic live rendering must stay silent by default.
- The live output must be conversation-oriented, not a Python object repr.
- The live output must contain only the exchange produced by the current action. It must not replay the entire prior session.
- Continuing an existing session must therefore show only the newly appended turns and tool activity.
- The live output must not expose the system prompt, dynamic context, tool inventory, prompt extensions, or other prompt-construction internals. But it still absolutely must render the agent's messages, tool calls, and runtime system events.
- When live rendering is enabled, the returned `Session` object from the same expression must not also auto-render as a full inspected session in REPL or Jupyter. `"Hi" >> agent` is the hardest case here because it returns `Session`, but only the compact live view must be shown.
- Live rendering must be enabled by default in REPL and Jupyter environments.
- Live rendering in ordinary single-session program execution must be part of the supported behavior for `"Hi" >> agent` and `"Hi" >> session`, but only by default when stdout is an attached TTY.
- Users must be able to disable script live rendering without affecting REPL or Jupyter defaults.
- Users must also be able to disable live rendering for REPL and Jupyter when they want silent runs there too.
- The live-rendering settings API must operate per mode, and each mode must have an explicit documented default that can be restored.
- `Agent.parallel(...)` must remain excluded from automatic live rendering.
- Parallel runs must keep live rendering disabled by default.

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

- In a Python REPL or terminal IPython session, evaluating `session` must show the full session representation through Rich.
- In Jupyter, evaluating `session` must show the full session representation as markdown and it must not include the live ipywidgets controls.
- In ordinary scripts, `print(session)` must show the full session representation in plain text by default, or in Rich-styled terminal output when the output channel supports it.
- `print(session)` must always remain available even if live rendering is disabled.
- The full view must include the complete conversation history, not only the most recent exchange.
- The full view must include the real OpenHands system prompt taken from the recorded event stream.
- If OpenHands recorded dynamic context alongside the system prompt, that dynamic context must also be shown.
- If prompt extensions or other message-level context were injected into the conversation events, the full view must show them as part of the session representation.
- The full view must remain formatted for humans; it must not degrade into an unstructured debug dump.
- HTML-specific full-session rendering is removed from the public API and from the display hooks for this task.

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
- Users who disable automatic live rendering must still be able to inspect the full session afterward.
- The implementation must keep the distinction between a live-rendered session-changing expression and an explicitly inspected `Session`, even though both values are the same runtime object type.

#### Notes

- The compact public renderers should stay compact and conversation-focused rather than silently changing into full prompt dumps.
- The full session view must be derived from the actual OpenHands events, including the OpenHands system-prompt event, rather than from reconstructed or guessed prompt text.
- The task should define ordinary script execution explicitly instead of leaving it implicit: non-parallel `"prompt" >> agent` runs with attached TTY output are part of the live-rendering UX, while redirected stdout stays silent by default.
- Automatic live rendering must remain opt-out for users who want quiet execution.
- Jupyter live output must keep ipywidgets in the live path, but explicit full-session inspection in Jupyter must be markdown-only and widget-free.
- The task removes HTML-specific session rendering instead of preserving a secondary format that is no longer part of the desired UX.
- The default visible representation of `Session` during explicit inspection should be the full pretty session view, not a raw Python-object representation.
- The live-rendering settings API should avoid stringly-typed mode names where a stable enum can make the contract clearer.

### Review notes

1. Tightened the task to one problem area only: session representation in interactive environments, rather than mixing it with unrelated notebook interaction features.
2. Made the current behavior vs desired behavior explicit by naming the existing suppression path, the notebook output mismatch, and the missing `SystemPromptEvent` coverage in pyflow renderers.
3. Split the requirements into two user-facing views, because the user explicitly wants live conversation output to hide system prompts while explicit session inspection must show them.
4. Added concrete examples for `>> agent`, `>> session`, bare `session`, and `print(session)` so the desired behavior is unambiguous before implementation planning begins.
5. Clarified the scope boundaries that matter for implementation review: no automatic live rendering for parallel runs, no notebook input controls in the live path, no raw object dump as the default visible session representation, and no replay of the full prior transcript during continuation updates.
6. Expanded the spec so ordinary foreground `python` execution is explicitly covered, not just REPL and notebook behavior.
7. Added the requirement that automatic live rendering must be configurable per environment, so script live rendering can be disabled without forcing the same policy on REPL and Jupyter.
8. Fixed ordinary script defaults so attached-TTY runs live-render by default, while redirected stdout remains silent by default.
9. Removed HTML rendering from the task entirely and standardized the desired outputs on Rich, plain text, and markdown only.
10. Corrected the notebook requirement to keep live ipywidgets in the live path while ensuring explicit notebook inspection is markdown-only and widget-free.
11. Replaced stringly-typed mode identifiers in the plan with enums where the distinction is core to the runtime contract.

## Implementation

1. Remove the HTML session-rendering branch and keep only terminal-oriented text/Rich output plus notebook markdown output.
2. Split session rendering into explicit compact live output and explicit full inspection output.
3. Move live-rendering policy and duplicate-suppression into `pyflow.display`, with per-environment settings.
4. Change runtime call sites to pass the event boundary for the current action, so live output can render only newly appended turns.
5. Keep notebook live widgets in the live path, but separate them from explicit full notebook inspection.

### 1. Remove HTML session rendering and keep text, Rich, and markdown only

#### Files: `pyflow/session.py`, `pyflow/session_rendering.py`, `tests/test_runtime.py`, `tests/fixtures/session_html_transcript.txt`

The current code still carries a full HTML renderer and HTML-specific session hooks. The revised task removes that branch entirely and standardizes the outputs on terminal text/Rich plus notebook markdown.

- In `pyflow/session.py`, remove:
  - `Session.render_html`
  - `Session.display_html`
  - `Session._repr_html_`
  - HTML-specific branches in `_repr_mimebundle_`
- In `pyflow/session_rendering.py`, remove:
  - `SessionTranscript.render_html`
  - all `_render_html_*` helpers
  - the embedded HTML/CSS session stylesheet
- In the tests and fixtures, remove all HTML snapshot coverage, including `tests/fixtures/session_html_transcript.txt`.
- Do not replace HTML with another secondary browser-only format. The supported inspection formats after this task are:
  - Rich for terminal display
  - plain text for non-rich script output
  - markdown for notebook display

### 2. Introduce explicit compact vs full session renderers

#### File: `pyflow/session_rendering.py`

Keep this module as the authoritative builder for terminal-oriented transcript output, but stop treating every render consumer as the same view.

- Add `SystemPromptEvent` to the imported OpenHands event types.
- Extend the internal transcript model so a turn can carry labeled detail sections in addition to plain messages and tool calls. The sections are required for the full view because the system prompt, dynamic context, prompt extensions, and tool inventory must render as structured labeled blocks rather than as one flattened message blob.
- Do not introduce new public transcript types. Keep the transcript classes private-to-module in spirit and drive the new behavior through builder arguments and rendering methods.
- Add an internal render-view enum instead of a `Literal` string selector:

```python
class _SessionRenderView(StrEnum):
    LIVE = "live"
    FULL = "full"
```

- Change `build_transcript(...)` to accept:

```python
def build_transcript(
    events: Sequence[Event],
    *,
    execution_status: str | None = None,
    view: _SessionRenderView = _SessionRenderView.LIVE,
) -> SessionTranscript:
```

- Live view rules:
  - Preserve current conversation-focused behavior.
  - Continue to ignore `SystemPromptEvent`.
  - Continue to show user, agent, system runtime events, and tool calls.
  - Continue to omit prompt-construction internals such as dynamic context, prompt extensions, and tool inventory.
- Full view rules:
  - Render `SystemPromptEvent` as a `system` turn.
  - Represent the static system prompt as a labeled section named `System Prompt`.
  - If `dynamic_context` exists, render it as a separate labeled section named `Dynamic Context`.
  - Render the tool inventory from the event as a separate labeled section named `Tools`, using one readable line per tool with the tool name and the first line of its description.
  - For `MessageEvent`, if `extended_content` is present, keep the normal message text and append a labeled section named `Prompt Extension`.
  - Keep existing runtime system events (`HookExecutionEvent`, `PauseEvent`) visible in both views.
  - Do not emit raw Python reprs of OpenHands objects.
- Update the rendering methods on `SessionTranscript` so they can render labeled sections in both supported terminal output formats:
  - `render_text()` prints section headers inline under the turn.
  - `__rich_console__()` renders sections as readable sub-blocks, using `Syntax` for code-like content and plain `Text` otherwise.
- Keep `render_text()` and `__rich_console__()` as the live-rendering behavior for transcripts built with `view=_SessionRenderView.LIVE`. Full rendering is achieved by building a full transcript, not by mutating the meaning of the live methods.

### 3. Expose full inspection APIs on `Session`

#### File: `pyflow/session.py`

Keep the existing compact render methods public and add explicit full render methods for inspection. Also make the environment-specific explicit inspection behavior match the user-facing requirements exactly.

- Add private helpers rather than new public properties:

```python
def _build_transcript(
    self,
    *,
    view: _SessionRenderView,
) -> SessionTranscript:
    ...
```

- Keep:
  - `Session.render()` compact plain text
  - `Session.render_markdown()` compact notebook/live markdown
- Add the new public methods from the task spec:
  - `Session.render_full()`
  - `Session.render_full_markdown()`
- Make `Session.__str__()` environment-sensitive for explicit inspection:
  - in Jupyter, return `self.render_full_markdown()`
  - in non-notebook terminal contexts, return the full session as terminal output, using Rich-rendered ANSI text when the active stdout channel supports it and plain text otherwise
- `Session.render_full()` should remain a deterministic full plain-text render independent of environment. `__str__()` may choose a richer terminal representation on top of it for user-facing printing.
- Change `Session.__repr__()` as follows:
  - In REPL and terminal IPython explicit inspection, make the returned object render through the Rich display path, not through a raw repr string.
  - In Jupyter explicit inspection, return the full markdown representation through the notebook markdown hooks.
  - When the value is marked for same-expression live-output suppression, return the empty string or empty notebook payload so the compact live output remains the only visible output for `"prompt" >> agent` and `"prompt" >> session`.
  - In ordinary common CLI code paths where no interactive display hook is involved, keep the current object-style repr fallback.
- Change `_repr_markdown_()` and `_repr_mimebundle_()` to use the full markdown render variant for explicit session inspection in notebooks.
- Change `Session.__rich_console__()` and `Session.display()` to render the full transcript, because both are explicit inspection paths.
- Do not add `display_full_*` methods in this task. The two `render_full*` methods are sufficient, and `display()` plus `display_markdown()` should become inspection-oriented by calling the full renderers.

### 4. Centralize live-rendering policy, per-environment settings, and duplicate suppression

#### File: `pyflow/display.py`

This module should become the single place where pyflow decides whether an action should auto-render live output.

- Add a public enum for the settings API:

```python
class LiveRenderingTarget(StrEnum):
    SCRIPT = "script"
    REPL = "repl"
    NOTEBOOK = "notebook"
```

- Store overrides keyed by that enum:

```python
_live_rendering_overrides: dict[LiveRenderingTarget, bool | None]
```

- Add the new public API:

```python
def set_live_rendering(
    mode: LiveRenderingTarget,
    enabled: bool | None,
) -> None:
    ...
```

- Behavior of `set_live_rendering`:
  - `set_live_rendering(LiveRenderingTarget.SCRIPT, False)` disables live rendering only for ordinary script execution and leaves REPL and Jupyter defaults untouched.
  - `set_live_rendering(LiveRenderingTarget.REPL, False)` disables live rendering for Python REPL and terminal IPython.
  - `set_live_rendering(LiveRenderingTarget.NOTEBOOK, False)` disables live rendering for Jupyter.
  - `set_live_rendering(mode, True)` forces live rendering on for that mode.
  - `set_live_rendering(mode, None)` restores that mode's default behavior.
  - The function intentionally changes only one mode per call so the caller never has to respecify unrelated modes.
- Add internal helpers:

```python
def _stdout_is_tty() -> bool: ...
def _live_render_enabled(environment: DisplayEnvironment) -> bool: ...
def _live_render_setting_key(environment: DisplayEnvironment) -> LiveRenderingTarget: ...
def _default_live_rendering(mode: LiveRenderingTarget) -> bool: ...
```

- Default policy, expressed through `_default_live_rendering(...)`:
  - `LiveRenderingTarget.REPL`: enabled by default
  - `LiveRenderingTarget.NOTEBOOK`: enabled by default
  - `LiveRenderingTarget.SCRIPT`: enabled only when `sys.stdout.isatty()` is true
  - redirected stdout or non-TTY common CLI therefore maps to `LiveRenderingTarget.SCRIPT` with a default value of `False`
- Keep `DisplayEnvironment` unchanged. Do not add a separate enum value for TTY-vs-redirected common CLI; resolve that as policy, not as a new environment class.
- Replace `_pending_repl_values` with a generalized pending-live-output store that is used for REPL, IPython, and notebook same-expression suppression.
- Add an internal suppression query usable from `Session.__repr__()` and notebook repr hooks:

```python
def should_suppress_live_inspection(session: Session) -> bool: ...
```

- Keep notebook execution-count scoping for notebook suppression so the suppression only lasts for the current cell.
- Keep the plain REPL displayhook installed by `install_rich_pretty`, but change its behavior so it suppresses only duplicate auto-display after a live render, rather than suppressing the live render itself.
- The suppression mechanism must explicitly cover the hardest case noted in the task: `"Hi" >> agent` and `"Hi" >> session` both return `Session`, but when live rendering is enabled they must not immediately trigger a second full-session auto-display in REPL or Jupyter.

### 5. Render compact deltas from runtime call sites

#### Files: `pyflow/agent.py`, `pyflow/session.py`, `pyflow/display.py`

Live output must show only the newly appended exchange for the current action, not the whole session.

- Change `sync_interactive_session` to accept the event boundary:

```python
def sync_interactive_session(
    session: Session,
    *,
    start_event_index: int,
) -> None:
    ...
```

- Inside `sync_interactive_session`:
  - build the compact live output from `session.events[start_event_index:]`
  - render that compact delta immediately when `_live_render_enabled(...)` is true
  - mark the returned `Session` for duplicate-display suppression when the current statement or cell will also auto-display it
- Runtime call-site rules:
  - `Agent._run_request(...)`: after the run finishes, call `sync_interactive_session(session, start_event_index=0)` so the first live render includes the user message and the new response but still omits the system prompt because compact view filters it out.
  - `Session.__rrshift__(...)`: capture `start_event_index = len(self.events)` before `append_message(...)`, then call `sync_interactive_session(..., start_event_index=start_event_index)` after `conversation.run()`.
  - `Session.approve_pending_actions(...)`, `Session.reject_pending_actions(...)`, and `Session.pause(...)`: capture `start_event_index = len(self.events)` before mutating the conversation and pass it through after the action completes.
- Do not change `Agent.parallel(...)` or `_run_parallel_worker(...)`. The current `interactive=False` boundary stays in place, and no live render call should be introduced on the parallel path.

### 6. Make notebook live output current-cell, compact, and widget-backed

#### File: `pyflow/notebook_visualizer.py`

Automatic notebook live rendering and explicit notebook inspection must stop sharing the same output primitive, but the live notebook path must keep ipywidgets controls.

- Keep `NotebookLiveControls` in the automatic live notebook path.
- Keep `NotebookSessionWidget` only for explicit read-only widget rendering through `Session.render_widget()`.
- Keep `NotebookDisplayTarget.display_controls(...)`, because live notebook output must still include widgets.
- Change `_IPythonNotebookTarget` to use an IPython display handle for the current cell rather than a persistent widget anchored to the first output cell:
  - on first display in the current run, create a display handle with `display_markdown(..., raw=True, display_id=True)`
  - on later updates in the same run, update the same handle
  - render the live controls in the current cell as part of the live output path
  - do not reuse the explicit read-only widget path for automatic live rendering
- Add compact/full notebook markdown builders instead of one implicit builder:

```python
def notebook_markdown_for_session_delta(session: Session, *, start_event_index: int) -> str: ...
def notebook_markdown_for_session(session: Session) -> str: ...
def notebook_full_markdown_for_session(session: Session) -> str: ...
```

- Compact live notebook markdown rules:
  - use only `session.events[start_event_index:]`
  - omit `SystemPromptEvent`, dynamic context, prompt extensions, and tool inventory
  - keep user/agent/system runtime turns and tool calls
- Full notebook markdown rules:
  - render the full session
  - include system prompt, dynamic context, prompt extensions, and tool inventory in labeled expandable sections
- Change `notebook_mimebundle_for_session(...)` and the notebook explicit inspection hooks to use the full notebook markdown plus the full plain-text render.
- `sync_notebook_session(...)` should accept `start_event_index` and be responsible only for the compact live delta display plus the live controls in the current cell. It should not reuse the explicit read-only widget as part of automatic live rendering; `render_widget()` remains an explicit read-only call.
- Explicit notebook inspection through `session` or `print(session)` must never include the live controls widget.

### 7. Export the override API

#### File: `pyflow/__init__.py`

- Export `set_live_rendering` from `pyflow.display`.
- Add `"set_live_rendering"` to `__all__`.
- Do not export additional live-rendering helpers in this task.

### Review notes

1. Replaced the single global live-rendering override with per-environment settings because the task now explicitly requires disabling script live rendering independently from REPL and Jupyter.
2. Removed HTML handling from the implementation entirely instead of preserving a public branch that is no longer part of the desired behavior.
3. Kept compact rendering in `Session.render()` and `Session.render_markdown()`, and moved inspection behavior to `render_full*`, `__str__`, `__rich_console__`, and the notebook markdown hooks.
4. Chose event-boundary-based delta rendering (`start_event_index`) as the mechanism for live output, because it solves continuation rendering without introducing mutable transcript diff state on `Session`.
5. Kept notebook live controls in the live path and separated them from explicit notebook inspection, matching the updated task requirements.
6. Replaced both the live/full render selector and the live-rendering mode keys with enums so the implementation does not rely on string literals for core runtime distinctions.

## Testing

Tests should be added in four groups:

1. display-policy and duplicate-suppression tests
2. session inspection rendering tests
3. notebook live-rendering and inspection tests
4. cleanup tests for removed HTML behavior

### File: `tests/test_display.py`

#### Test case: default live-rendering policy enables REPL live output

Property:

- for `DisplayEnvironment.PYTHON_REPL`, live rendering is enabled by default
- the same default also applies to terminal IPython because it follows the REPL-style live path

#### Test case: default live-rendering policy enables notebook live output

Property:

- for `DisplayEnvironment.JUPYTER`, live rendering is enabled by default

#### Test case: default live-rendering policy enables script live output only for TTY stdout

Property:

- for `DisplayEnvironment.COMMON_CLI` with attached TTY stdout, live rendering is enabled by default
- for `DisplayEnvironment.COMMON_CLI` with redirected or non-TTY stdout, live rendering is disabled by default

#### Test case: `set_live_rendering(LiveRenderingTarget.SCRIPT, False)` disables only script live output

Property:

- after disabling only `script`, common CLI live rendering is disabled
- REPL and notebook defaults remain enabled

#### Test case: `set_live_rendering(LiveRenderingTarget.REPL, False)` disables REPL live output only

Property:

- REPL live rendering is disabled
- notebook and script defaults remain unchanged

#### Test case: `set_live_rendering(LiveRenderingTarget.NOTEBOOK, False)` disables notebook live output only

Property:

- notebook live rendering is disabled
- REPL and script defaults remain unchanged

#### Test case: resetting an override restores defaults

Property:

- `set_live_rendering(mode, None)` restores that mode to its explicit documented default behavior
- other previously configured environment keys are preserved

#### Test case: default policy helper returns the documented per-mode defaults

Property:

- `LiveRenderingTarget.REPL` resolves to enabled by default
- `LiveRenderingTarget.NOTEBOOK` resolves to enabled by default
- `LiveRenderingTarget.SCRIPT` resolves based on TTY detection

#### Test case: live-rendered REPL result suppresses immediate duplicate session inspection

Property:

- when live rendering is enabled and the current REPL statement will auto-display its result, `"Hi" >> agent` or `"Hi" >> session` marks the returned `Session` for suppression
- the later displayhook path does not render a second full-session inspection for that same expression result

#### Test case: live-rendered notebook result suppresses immediate duplicate session inspection

Property:

- when live rendering is enabled and the current notebook cell would auto-display its result, `"Hi" >> agent` or `"Hi" >> session` marks the returned `Session` for suppression
- the notebook repr path does not emit a second full-session markdown payload for that same expression result

### File: `tests/test_runtime.py`

#### Test case: compact plain-text session rendering excludes prompt-construction internals

Property:

- `Session.render()` shows the conversation-focused compact view
- the compact view excludes the system prompt, dynamic context, tool inventory, and prompt extensions

#### Test case: full plain-text session rendering includes prompt-construction internals

Property:

- `Session.render_full()` includes the real system prompt from `SystemPromptEvent`
- `Session.render_full()` includes dynamic context when present
- `Session.render_full()` includes prompt extensions when present
- `Session.render_full()` includes the tool inventory when present

#### Test case: explicit Rich inspection renders the full session

Property:

- `console.print(session)` renders the full session, not the compact live view
- the Rich output includes the system prompt and the rest of the full history

#### Test case: `print(session)` in terminal contexts produces full-session inspection output

Property:

- the string form used for `print(session)` is the full session inspection output
- the output is plain text or Rich-compatible terminal text depending on the simulated output channel

#### Test case: compact live delta rendering shows only newly appended turns

Property:

- a continuation on an existing session renders only the turns and tool activity added after the saved `start_event_index`
- previously existing turns are not replayed in the compact live output

#### Test case: full inspection remains available after live rendering is disabled

Property:

- after disabling live rendering through the settings API, `print(session)` and explicit session inspection still render the full session correctly

#### Test case: HTML session APIs are removed

Property:

- `Session` no longer exposes `render_html` or `display_html`
- runtime notebook or terminal inspection no longer depends on `_repr_html_`

### File: `tests/test_notebook_visualizer.py`

#### Test case: compact notebook delta builder excludes prompt-construction internals

Property:

- the notebook live delta builder excludes `SystemPromptEvent`, dynamic context, prompt extensions, and tool inventory
- it still includes user messages, agent messages, runtime system events, and tool calls for the current action

#### Test case: full notebook markdown builder includes prompt-construction internals

Property:

- the full notebook markdown builder includes the real system prompt
- it includes dynamic context, prompt extensions, and tool inventory when present

#### Test case: live notebook visualizer renders transcript and widgets together

Property:

- the automatic live notebook path renders the compact markdown transcript
- the automatic live notebook path also renders the ipywidgets controls

#### Test case: explicit notebook session markdown is widget-free

Property:

- explicit full notebook inspection produces markdown only
- the resulting explicit inspection output does not include the live controls widget

#### Test case: notebook live updates stay scoped to the current action

Property:

- a later continuation of the same session renders only the new notebook delta
- earlier turns are not replayed as part of the live notebook update

### File: `tests/test_notebook_integration.py`

#### Test case: notebook live run renders current-cell markdown plus widgets

Property:

- a cell containing `"Hi" >> agent` produces a compact markdown live transcript in that cell
- the same cell also produces the live ipywidgets output

#### Test case: explicit notebook session inspection renders full markdown without widgets

Property:

- a later `session` cell renders the full session as markdown
- that explicit inspection output does not include an ipywidgets payload

#### Test case: live notebook expression does not also auto-display the returned session

Property:

- a cell containing `"Hi" >> agent` produces only the live output for that action
- the returned `Session` object is not also auto-rendered as a second full notebook inspection payload in the same cell

#### Test case: notebook live rendering can be disabled independently

Property:

- after `set_live_rendering(notebook=False)`, a live notebook run no longer auto-renders the compact live output
- explicit later `session` inspection still renders the full markdown session

### File: `tests/fixtures/`

#### Fixture updates

Property:

- remove the obsolete HTML snapshot fixture
- add or update snapshots for full plain-text inspection, Rich inspection, and full notebook markdown where needed

### Review notes

1. Reworked the testing section around the exact output matrix you specified instead of mirroring the earlier HTML-capable implementation draft.
2. Added explicit suppression tests for the hard case where a session-changing expression returns `Session` but must not auto-display that returned session when live rendering is already shown.
3. Added dedicated cleanup coverage for HTML removal so the deletion is part of the tested scope rather than an unverified side effect.
