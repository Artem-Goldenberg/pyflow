from __future__ import annotations

import builtins
import dis
import importlib
import sys
import weakref
from enum import StrEnum
from types import FrameType

from rich.console import Console


_pending_repl_values: dict[int, weakref.ReferenceType[object]] = {}


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


def mark_live_repl_value(value: object) -> None:
    """Mark a value as already shown by live terminal output in this REPL turn."""
    if detect_display_environment() is not DisplayEnvironment.PYTHON_REPL:
        return
    if not _current_repl_statement_will_print_expression():
        return
    try:
        _pending_repl_values[id(value)] = weakref.ref(value)
    except TypeError:
        return


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
