from __future__ import annotations

import ast
import builtins
import dis
import importlib
import sys
import weakref
from enum import StrEnum
from types import FrameType
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from openhands.sdk.conversation.visualizer.base import ConversationVisualizerBase
    from pyflow.session import Session


_pending_repl_values: dict[int, weakref.ReferenceType[object]] = {}
_pending_notebook_values: dict[int, tuple[weakref.ReferenceType[object], int]] = {}


class DisplayEnvironment(StrEnum):
    COMMON_CLI = "common_cli"
    PYTHON_REPL = "python_repl"
    IPYTHON = "ipython"
    JUPYTER = "jupyter"

    @property
    def is_interactive(self) -> bool:
        return self is not DisplayEnvironment.COMMON_CLI


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
        if _consume_pending_repl_value(value):
            builtins._ = value  # type: ignore[attr-defined]
            return
        target.print(value)
        builtins._ = value  # type: ignore[attr-defined]

    sys.displayhook = display_hook


def conversation_visualizer_for_environment() -> "ConversationVisualizerBase | None":
    """Return the environment-specific OpenHands visualizer, if any."""
    if detect_display_environment() is not DisplayEnvironment.JUPYTER:
        return None

    from pyflow.notebook_visualizer import NotebookConversationVisualizer
    from pyflow.runtime_logging import apply_default_jupyter_backend_log_policy

    apply_default_jupyter_backend_log_policy()
    return NotebookConversationVisualizer()


def sync_interactive_session(session: "Session") -> None:
    """Synchronize interactive display state after a session-changing action."""
    environment = detect_display_environment()
    if environment is DisplayEnvironment.JUPYTER:
        _sync_notebook_session(session)
        if _current_notebook_cell_will_display_expression():
            _mark_pending_notebook_value(session)
        return

    if environment is DisplayEnvironment.PYTHON_REPL:
        if _current_repl_statement_will_print_expression():
            _mark_pending_value(_pending_repl_values, session)


def should_suppress_notebook_display(value: object) -> bool:
    """Return whether notebook auto-display should be suppressed for this value."""
    return _has_pending_notebook_value(_pending_notebook_values, value)


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
    reference = _pending_repl_values.pop(id(value), None)
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


def _sync_notebook_session(session: "Session") -> None:
    from pyflow.notebook_visualizer import sync_notebook_session

    sync_notebook_session(session)


def _current_notebook_cell_will_display_expression() -> bool:
    shell = _get_ipython_shell()
    if shell is None:
        return False

    source = _current_notebook_cell_source(shell)
    if source is None:
        return False

    return _cell_source_will_display_expression(source)


def _current_notebook_cell_source(shell: object) -> str | None:
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
