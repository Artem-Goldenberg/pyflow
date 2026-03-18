from __future__ import annotations

import builtins
import io
import sys

import pytest
from rich.console import Console
from rich.text import Text

from pyflow.display import (
    DisplayEnvironment,
    _consume_pending_repl_value,
    detect_display_environment,
    install_rich_pretty,
    mark_live_repl_value,
)


def test_detect_display_environment_defaults_to_common_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: None)
    monkeypatch.delattr(sys, "ps1", raising=False)

    assert detect_display_environment() is DisplayEnvironment.COMMON_CLI


def test_detect_display_environment_detects_python_repl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: None)
    monkeypatch.setattr(sys, "ps1", ">>> ", raising=False)

    assert detect_display_environment() is DisplayEnvironment.PYTHON_REPL


def test_detect_display_environment_detects_ipython(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pyflow.display._get_ipython_shell",
        lambda: _terminal_ipython_shell(),
    )
    monkeypatch.delattr(sys, "ps1", raising=False)

    assert detect_display_environment() is DisplayEnvironment.IPYTHON


def test_detect_display_environment_detects_jupyter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pyflow.display._get_ipython_shell",
        lambda: _jupyter_shell(),
    )
    monkeypatch.delattr(sys, "ps1", raising=False)

    assert detect_display_environment() is DisplayEnvironment.JUPYTER


def test_install_rich_pretty_delegates_to_rich_install_in_ipython(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_console: Console | None = None

    class _PrettyModule:
        @staticmethod
        def install(*, console: Console | None = None) -> None:
            nonlocal observed_console
            observed_console = console

    console = Console()
    monkeypatch.setattr(
        "pyflow.display._get_ipython_shell",
        lambda: _terminal_ipython_shell(),
    )
    monkeypatch.setattr(
        "rich.pretty.install",
        _PrettyModule.install,
    )

    install_rich_pretty(console=console)

    assert observed_console is console


def test_install_rich_pretty_installs_plain_repl_displayhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=80)
    previous_displayhook = sys.displayhook
    previous_last_value = getattr(builtins, "_", None)

    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: None)

    install_rich_pretty(console=console)
    sys.displayhook(_DemoRenderable())

    assert "demo" in buffer.getvalue()
    assert isinstance(getattr(builtins, "_"), _DemoRenderable)

    sys.displayhook = previous_displayhook
    builtins._ = previous_last_value  # type: ignore[attr-defined]


def test_install_rich_pretty_suppresses_immediate_echo_for_live_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=80)
    previous_displayhook = sys.displayhook
    previous_last_value = getattr(builtins, "_", None)
    value = _DemoRenderable()

    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: None)
    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )
    monkeypatch.setattr(
        "pyflow.display._current_repl_statement_will_print_expression",
        lambda: True,
    )

    install_rich_pretty(console=console)
    mark_live_repl_value(value)
    sys.displayhook(value)

    assert buffer.getvalue() == ""
    assert builtins._ is value  # type: ignore[attr-defined]

    sys.displayhook = previous_displayhook
    builtins._ = previous_last_value  # type: ignore[attr-defined]


def test_mark_live_repl_value_ignores_assignment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _DemoRenderable()

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )
    monkeypatch.setattr(
        "pyflow.display._current_repl_statement_will_print_expression",
        lambda: False,
    )

    mark_live_repl_value(value)

    assert not _consume_pending_repl_value(value)


def _terminal_ipython_shell() -> object:
    class TerminalInteractiveShell:
        pass

    TerminalInteractiveShell.__module__ = "IPython.terminal.interactiveshell"
    return TerminalInteractiveShell()


def _jupyter_shell() -> object:
    class ZMQInteractiveShell:
        pass

    ZMQInteractiveShell.__module__ = "ipykernel.zmqshell"
    return ZMQInteractiveShell()


class _DemoRenderable:
    def __rich__(self) -> Text:
        return Text("demo")
