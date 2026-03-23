from __future__ import annotations

import ast
import builtins
import dis
import importlib
import sys
import weakref
from enum import StrEnum
from types import FrameType
from typing import TYPE_CHECKING, cast

from openhands.sdk.conversation.visualizer.base import ConversationVisualizerBase
from openhands.sdk.conversation.visualizer.default import DefaultConversationVisualizer
from openhands.sdk.event.base import Event
from openhands.sdk.event import MessageEvent, ObservationEvent, SystemPromptEvent
from rich.console import Console

from pyflow.session_rendering import _SessionRenderView, build_transcript

if TYPE_CHECKING:
    from openhands.sdk.conversation.base import BaseConversation, ConversationStateProtocol
    from pyflow.session import Session


_pending_terminal_values: dict[int, weakref.ReferenceType[object]] = {}
_pending_notebook_values: dict[int, tuple[weakref.ReferenceType[object], int]] = {}


class DisplayEnvironment(StrEnum):
    COMMON_CLI = "common_cli"
    PYTHON_REPL = "python_repl"
    IPYTHON = "ipython"
    JUPYTER = "jupyter"

    @property
    def is_interactive(self) -> bool:
        return self is not DisplayEnvironment.COMMON_CLI


class LiveRenderingTarget(StrEnum):
    SCRIPT = "script"
    REPL = "repl"
    NOTEBOOK = "notebook"


_live_rendering_overrides: dict[LiveRenderingTarget, bool | None] = {
    LiveRenderingTarget.SCRIPT: None,
    LiveRenderingTarget.REPL: None,
    LiveRenderingTarget.NOTEBOOK: None,
}


class TerminalConversationVisualizer(DefaultConversationVisualizer):
    """Render the current live session segment incrementally in terminal shells."""

    def __init__(self) -> None:
        super().__init__(skip_user_messages=True)

    def begin_session_render(self, *, start_event_index: int) -> None:
        return None

    def on_event(self, event: Event) -> None:
        if isinstance(event, SystemPromptEvent):
            return
        if isinstance(event, ObservationEvent):
            return
        if (
            isinstance(event, MessageEvent)
            and event.llm_message is not None
            and event.llm_message.role == "user"
        ):
            return
        output = self._create_event_block(event)
        if output is None:
            return
        self._console.print(output)

    def finish_session_render(self) -> None:
        return None


def detect_display_environment() -> DisplayEnvironment:
    shell = _get_ipython_shell()
    if shell is not None:
        shell_class = shell.__class__
        if shell_class.__name__ == "ZMQInteractiveShell":
            return DisplayEnvironment.JUPYTER
        return DisplayEnvironment.IPYTHON

    if getattr(sys, "ps1", None) is not None:
        return DisplayEnvironment.PYTHON_REPL

    return DisplayEnvironment.COMMON_CLI


def install_rich_pretty(console: Console | None = None) -> None:
    """Install Rich pretty-printing for interactive REPL display."""
    if _get_ipython_shell() is not None:
        from rich.pretty import install

        install(console=console)
        return

    target = console if console is not None else Console()

    def display_hook(value: object) -> None:
        if value is None:
            return
        builtins._ = None  # type: ignore[attr-defined]
        if _consume_pending_terminal_value(value):
            builtins._ = value  # type: ignore[attr-defined]
            return
        target.print(value)
        builtins._ = value  # type: ignore[attr-defined]

    sys.displayhook = display_hook


def conversation_visualizer_for_environment() -> "ConversationVisualizerBase | None":
    """Return the environment-specific OpenHands visualizer, if any."""
    environment = detect_display_environment()
    if not _live_render_enabled(environment):
        return None

    if environment is DisplayEnvironment.JUPYTER:
        from pyflow.notebook_visualizer import NotebookConversationVisualizer
        from pyflow.runtime_logging import apply_default_jupyter_backend_log_policy

        apply_default_jupyter_backend_log_policy()
        return NotebookConversationVisualizer()

    if environment in {DisplayEnvironment.PYTHON_REPL, DisplayEnvironment.IPYTHON}:
        return TerminalConversationVisualizer()

    return None


def prepare_live_render(
    conversation: "BaseConversation",
    *,
    start_event_index: int,
) -> None:
    """Reset the environment visualizer before a new live-rendered action starts."""
    visualizer = _conversation_visualizer(conversation)
    starter = getattr(visualizer, "begin_session_render", None)
    if callable(starter):
        starter(start_event_index=start_event_index)


def set_live_rendering(
    mode: LiveRenderingTarget,
    enabled: bool | None,
) -> None:
    """Override or restore live-rendering behavior for one environment mode."""
    _live_rendering_overrides[mode] = enabled


def sync_interactive_session(
    session: "Session",
    *,
    start_event_index: int = 0,
) -> None:
    """Synchronize interactive display state after a session-changing action."""
    environment = detect_display_environment()
    if not _live_render_enabled(environment):
        return

    if environment is DisplayEnvironment.JUPYTER:
        _sync_notebook_session(session, start_event_index=start_event_index)
        if _current_notebook_cell_will_display_expression():
            _mark_pending_notebook_value(session)
        return

    if environment in {DisplayEnvironment.PYTHON_REPL, DisplayEnvironment.IPYTHON}:
        if _finish_terminal_live_render(session.conversation):
            if _interactive_input_will_display_expression(environment):
                _mark_pending_value(_pending_terminal_values, session)
            return

    transcript = build_transcript(
        session.events[start_event_index:],
        execution_status=session.execution_status,
        view=_SessionRenderView.LIVE,
    )
    if not transcript.turns:
        return

    if environment in {DisplayEnvironment.PYTHON_REPL, DisplayEnvironment.IPYTHON}:
        Console().print(transcript)
        if _interactive_input_will_display_expression(environment):
            _mark_pending_value(_pending_terminal_values, session)
        return

    rendered = transcript.render_text()
    if not rendered:
        return
    sys.stdout.write(rendered)
    if not rendered.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def should_suppress_live_inspection(value: object) -> bool:
    """Return whether this value should skip same-expression inspection display."""
    environment = detect_display_environment()
    if environment is DisplayEnvironment.JUPYTER:
        return _has_pending_notebook_value(_pending_notebook_values, value)
    if environment in {DisplayEnvironment.PYTHON_REPL, DisplayEnvironment.IPYTHON}:
        return _has_pending_value(_pending_terminal_values, value)
    return False


def should_suppress_notebook_display(value: object) -> bool:
    """Return whether notebook auto-display should be suppressed for this value."""
    return _has_pending_notebook_value(_pending_notebook_values, value)


def _stdout_is_tty() -> bool:
    isatty = getattr(sys.stdout, "isatty", None)
    if not callable(isatty):
        return False
    return bool(isatty())


def _live_render_enabled(environment: DisplayEnvironment) -> bool:
    mode = _live_render_setting_key(environment)
    override = _live_rendering_overrides[mode]
    if override is not None:
        return override
    return _default_live_rendering(mode)


def _live_render_setting_key(environment: DisplayEnvironment) -> LiveRenderingTarget:
    if environment is DisplayEnvironment.JUPYTER:
        return LiveRenderingTarget.NOTEBOOK
    if environment in {DisplayEnvironment.PYTHON_REPL, DisplayEnvironment.IPYTHON}:
        return LiveRenderingTarget.REPL
    return LiveRenderingTarget.SCRIPT


def _default_live_rendering(mode: LiveRenderingTarget) -> bool:
    if mode is LiveRenderingTarget.SCRIPT:
        return _stdout_is_tty()
    return True


def _get_ipython_shell() -> object | None:
    try:
        ipython = importlib.import_module("IPython")
    except ImportError:
        return None

    get_ipython = getattr(ipython, "get_ipython", None)
    if not callable(get_ipython):
        return None

    return get_ipython()


def _consume_pending_repl_value(value: object) -> bool:
    return _consume_pending_terminal_value(value)


def _consume_pending_terminal_value(value: object) -> bool:
    reference = _pending_terminal_values.pop(id(value), None)
    if reference is None:
        return False
    return reference() is value


def _has_pending_value(
    store: dict[int, weakref.ReferenceType[object]],
    value: object,
) -> bool:
    reference = store.get(id(value))
    if reference is None:
        return False
    return reference() is value


def _mark_pending_value(
    store: dict[int, weakref.ReferenceType[object]],
    value: object,
) -> bool:
    try:
        store[id(value)] = weakref.ref(value)
    except TypeError:
        return False
    return True


def _interactive_input_will_display_expression(
    environment: DisplayEnvironment,
) -> bool:
    if environment is DisplayEnvironment.PYTHON_REPL:
        return _current_repl_statement_will_print_expression()
    if environment is DisplayEnvironment.IPYTHON:
        source = _current_ipython_input_source(_get_ipython_shell())
        if source is None:
            return False
        return _cell_source_will_display_expression(source)
    return False


def _current_repl_statement_will_print_expression() -> bool:
    frame = _find_interactive_module_frame()
    if frame is None:
        return False

    next_instruction = _next_instruction(frame)
    if next_instruction is None:
        return False

    if next_instruction.opname == "PRINT_EXPR":
        return True
    return (
        next_instruction.opname == "CALL_INTRINSIC_1"
        and "INTRINSIC_PRINT" in next_instruction.argrepr
    )


def _find_interactive_module_frame() -> FrameType | None:
    frame = sys._getframe()
    while frame is not None:
        if frame.f_code.co_name == "<module>" and frame.f_code.co_filename.startswith("<"):
            return frame
        frame = frame.f_back
    return None


def _next_instruction(frame: FrameType) -> dis.Instruction | None:
    current_offset = frame.f_lasti
    for instruction in dis.get_instructions(frame.f_code):
        if instruction.offset > current_offset:
            return instruction
    return None


def _clear_pending_notebook_values(*args: object, **kwargs: object) -> None:
    del args, kwargs
    _pending_notebook_values.clear()


def _sync_notebook_session(
    session: "Session",
    *,
    start_event_index: int = 0,
) -> None:
    from pyflow.notebook_visualizer import sync_notebook_session

    sync_notebook_session(session, start_event_index=start_event_index)


def _current_notebook_cell_will_display_expression() -> bool:
    source = _current_ipython_input_source(_get_ipython_shell())
    if source is None:
        return False
    return _cell_source_will_display_expression(source)


def _current_ipython_input_source(shell: object | None) -> str | None:
    if shell is None:
        return None

    user_ns = getattr(shell, "user_ns", None)
    if isinstance(user_ns, dict):
        history = user_ns.get("In")
        if isinstance(history, list) and history:
            source = history[-1]
            if isinstance(source, str) and source.strip():
                return source

    history_manager = getattr(shell, "history_manager", None)
    input_hist_raw = getattr(history_manager, "input_hist_raw", None)
    if isinstance(input_hist_raw, list) and input_hist_raw:
        source = input_hist_raw[-1]
        if isinstance(source, str) and source.strip():
            return source

    return None


def _cell_source_will_display_expression(source: str) -> bool:
    stripped = source.rstrip()
    if not stripped or stripped.endswith(";"):
        return False

    try:
        module = ast.parse(source)
    except SyntaxError:
        return False

    if not module.body:
        return False

    return isinstance(module.body[-1], ast.Expr)


def _current_notebook_execution_count() -> int | None:
    shell = _get_ipython_shell()
    if shell is None:
        return None

    execution_count = getattr(shell, "execution_count", None)
    if isinstance(execution_count, int):
        return execution_count
    return None


def _mark_pending_notebook_value(value: object) -> bool:
    execution_count = _current_notebook_execution_count()
    if execution_count is None:
        return False

    try:
        reference = weakref.ref(value)
    except TypeError:
        return False

    _pending_notebook_values[id(value)] = (reference, execution_count)
    return True


def _has_pending_notebook_value(
    store: dict[int, tuple[weakref.ReferenceType[object], int]],
    value: object,
) -> bool:
    execution_count = _current_notebook_execution_count()
    if execution_count is None:
        return False

    entry = store.get(id(value))
    if entry is None:
        return False

    reference, marked_count = entry
    if marked_count != execution_count:
        return False
    return reference() is value


def _conversation_visualizer(
    conversation: "BaseConversation",
) -> ConversationVisualizerBase | None:
    return cast(ConversationVisualizerBase | None, getattr(conversation, "_visualizer", None))


def _finish_terminal_live_render(conversation: "BaseConversation") -> bool:
    visualizer = _conversation_visualizer(conversation)
    if not isinstance(visualizer, TerminalConversationVisualizer):
        return False
    visualizer.finish_session_render()
    return True


def _execution_status(state: "ConversationStateProtocol | None") -> str | None:
    if state is None:
        return None
    execution_status = getattr(state, "execution_status", None)
    return getattr(execution_status, "value", None)
