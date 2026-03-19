from __future__ import annotations

import builtins
import io
import sys
from typing import cast

import pytest
from rich.console import Console
from rich.text import Text

from pyflow.display import (
    DisplayEnvironment,
    _clear_pending_notebook_values,
    _consume_pending_repl_value,
    detect_display_environment,
    install_rich_pretty,
    should_suppress_notebook_display,
    sync_interactive_session,
)
from pyflow.session import Session


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


def test_sync_interactive_session_suppresses_immediate_repl_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=80)
    previous_displayhook = sys.displayhook
    previous_last_value = getattr(builtins, "_", None)
    session = _fake_session()

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
    sync_interactive_session(session)
    sys.displayhook(session)

    assert buffer.getvalue() == ""
    assert builtins._ is session  # type: ignore[attr-defined]

    sys.displayhook = previous_displayhook
    builtins._ = previous_last_value  # type: ignore[attr-defined]


def test_sync_interactive_session_ignores_repl_assignment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fake_session()

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )
    monkeypatch.setattr(
        "pyflow.display._current_repl_statement_will_print_expression",
        lambda: False,
    )

    sync_interactive_session(session)

    assert not _consume_pending_repl_value(session)


def test_sync_interactive_session_suppresses_immediate_notebook_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = _FakeIPythonShell()
    session = _fake_session()
    refreshed = False

    def mark_refreshed(session_value: object) -> None:
        nonlocal refreshed
        refreshed = session_value is session

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: shell)
    monkeypatch.setattr(
        "pyflow.display._current_notebook_cell_will_display_expression",
        lambda: True,
    )
    monkeypatch.setattr("pyflow.display._sync_notebook_session", mark_refreshed)

    sync_interactive_session(session)

    assert refreshed
    assert should_suppress_notebook_display(session)


def test_sync_interactive_session_notebook_suppression_clears_after_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = _FakeIPythonShell()
    session = _fake_session()

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: shell)
    monkeypatch.setattr(
        "pyflow.display._current_notebook_cell_will_display_expression",
        lambda: True,
    )
    monkeypatch.setattr("pyflow.display._sync_notebook_session", lambda session: None)

    sync_interactive_session(session)
    shell.execution_count += 1

    assert not should_suppress_notebook_display(session)


def test_sync_interactive_session_ignores_notebook_assignment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = _FakeIPythonShell()
    session = _fake_session()

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: shell)
    monkeypatch.setattr(
        "pyflow.display._current_notebook_cell_will_display_expression",
        lambda: False,
    )
    monkeypatch.setattr("pyflow.display._sync_notebook_session", lambda session: None)

    sync_interactive_session(session)

    assert not should_suppress_notebook_display(session)


def test_cell_source_will_display_expression_detects_assignment_vs_bare_expr() -> None:
    from pyflow.display import _cell_source_will_display_expression

    assert not _cell_source_will_display_expression('session = "Hi" >> agent')
    assert _cell_source_will_display_expression("session")
    assert not _cell_source_will_display_expression('"Hi" >> agent;')


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


class _FakeIPythonEvents:
    callbacks: list[tuple[str, object]]

    def __init__(self) -> None:
        self.callbacks = []

    def register(self, name: str, callback: object) -> None:
        self.callbacks.append((name, callback))


class _FakeIPythonShell:
    events: _FakeIPythonEvents
    execution_count: int

    def __init__(self) -> None:
        self.events = _FakeIPythonEvents()
        self.execution_count = 1


class _FakeSession:
    conversation: object

    def __init__(self) -> None:
        self.conversation = object()


def _fake_session() -> Session:
    return cast(Session, _FakeSession())
