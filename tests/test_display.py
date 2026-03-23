from __future__ import annotations

import builtins
import io
import sys
from typing import cast

import pytest
from openhands.sdk.conversation.base import ConversationStateProtocol
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from rich.console import Console
from rich.text import Text

from pyflow import Agent, Model, tool
from pyflow.display import (
    DisplayEnvironment,
    LiveRenderingTarget,
    TerminalConversationVisualizer,
    _clear_pending_notebook_values,
    _live_render_enabled,
    _consume_pending_repl_value,
    conversation_visualizer_for_environment,
    detect_display_environment,
    install_rich_pretty,
    set_live_rendering,
    should_suppress_notebook_display,
    sync_interactive_session,
)
from pyflow.session_rendering import SessionTranscript, SessionTurn
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
    capsys: pytest.CaptureFixture[str],
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
    monkeypatch.setattr(
        "pyflow.display.build_transcript",
        lambda *args, **kwargs: SessionTranscript(
            turns=(SessionTurn(role="agent", messages=["Done"]),),
        ),
    )

    install_rich_pretty(console=console)
    sync_interactive_session(session, start_event_index=0)
    sys.displayhook(session)

    assert "Done" in capsys.readouterr().out
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
    monkeypatch.setattr(
        "pyflow.display.build_transcript",
        lambda *args, **kwargs: SessionTranscript(
            turns=(SessionTurn(role="agent", messages=["Done"]),),
        ),
    )

    sync_interactive_session(session, start_event_index=0)

    assert not _consume_pending_repl_value(session)


def test_sync_interactive_session_suppresses_immediate_notebook_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = _FakeIPythonShell()
    session = _fake_session()
    refreshed = False

    def mark_refreshed(session_value: object, *, start_event_index: int = 0) -> None:
        nonlocal refreshed
        refreshed = session_value is session
        assert start_event_index == 0

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

    sync_interactive_session(session, start_event_index=0)

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
    monkeypatch.setattr(
        "pyflow.display._sync_notebook_session",
        lambda session, **kwargs: None,
    )

    sync_interactive_session(session, start_event_index=0)
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
    monkeypatch.setattr(
        "pyflow.display._sync_notebook_session",
        lambda session, **kwargs: None,
    )

    sync_interactive_session(session, start_event_index=0)

    assert not should_suppress_notebook_display(session)


def test_script_live_rendering_defaults_to_stdout_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pyflow.display._stdout_is_tty", lambda: True)
    assert _live_render_enabled(DisplayEnvironment.COMMON_CLI)

    monkeypatch.setattr("pyflow.display._stdout_is_tty", lambda: False)
    assert not _live_render_enabled(DisplayEnvironment.COMMON_CLI)


def test_set_live_rendering_overrides_only_requested_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pyflow.display._stdout_is_tty", lambda: True)

    set_live_rendering(LiveRenderingTarget.SCRIPT, False)
    try:
        assert not _live_render_enabled(DisplayEnvironment.COMMON_CLI)
        assert _live_render_enabled(DisplayEnvironment.PYTHON_REPL)
        assert _live_render_enabled(DisplayEnvironment.JUPYTER)
    finally:
        set_live_rendering(LiveRenderingTarget.SCRIPT, None)


def test_conversation_visualizer_for_environment_uses_terminal_visualizer_in_repl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )

    visualizer = conversation_visualizer_for_environment()

    assert isinstance(visualizer, TerminalConversationVisualizer)


def test_terminal_visualizer_skips_system_prompt_and_user_message() -> None:
    buffer = io.StringIO()
    visualizer = TerminalConversationVisualizer()
    visualizer._console = Console(file=buffer, force_terminal=False, width=80)
    session = _session_with_agent_reply()

    visualizer.initialize(cast(ConversationStateProtocol, session.conversation.state))

    for event in session.events[:3]:
        visualizer.on_event(event)

    rendered = buffer.getvalue()

    assert rendered
    assert not rendered.startswith("\n")
    assert "System Prompt" not in rendered
    assert "Hi" not in rendered
    assert "Agent Action" in rendered
    assert "Hello" in rendered


def test_terminal_visualizer_skips_observation_events() -> None:
    @tool(name="display_echo_filter_tool_test")
    def echo_tool(value: str) -> str:
        """Echo the provided value."""
        return f"OBS:{value}"

    model = Model.test(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="Thinking")],
                tool_calls=[
                    MessageToolCall(
                        id="call_echo",
                        name="display_echo_filter_tool_test",
                        arguments='{"value": "abc"}',
                        origin="completion",
                    )
                ],
            ),
            Message(
                role="assistant",
                content=[TextContent(text="Done")],
                tool_calls=[
                    MessageToolCall(
                        id="call_finish",
                        name="finish",
                        arguments='{"message": "done"}',
                        origin="completion",
                    )
                ],
            ),
        )
    )
    session = "use the tool" >> Agent(model=model, tools=(echo_tool,))
    buffer = io.StringIO()
    visualizer = TerminalConversationVisualizer()
    visualizer._console = Console(file=buffer, force_terminal=False, width=80)

    visualizer.initialize(cast(ConversationStateProtocol, session.conversation.state))

    for event in session.events:
        visualizer.on_event(event)

    rendered = buffer.getvalue()

    assert "Agent Action" in rendered
    assert "Thinking" in rendered
    assert "Done" in rendered
    assert "Observation ─" not in rendered
    assert "Tool:" not in rendered
    assert "OBS:abc" not in rendered


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
    events: tuple[object, ...]
    execution_status: str | None

    def __init__(self) -> None:
        self.conversation = object()
        self.events = ()
        self.execution_status = "finished"


def _fake_session() -> Session:
    return cast(Session, _FakeSession())


def _session_with_agent_reply() -> Session:
    model = Model.test(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="Hello")],
                tool_calls=[
                    MessageToolCall(
                        id="call_finish",
                        name="finish",
                        arguments='{"message": "Done"}',
                        origin="completion",
                    )
                ],
            ),
        )
    )
    return "Hi" >> Agent(model=model, tools=())
