from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Sequence, cast

import ipywidgets as widgets
import pytest
from openhands.sdk import Message, TextContent
from openhands.sdk.conversation.base import ConversationStateProtocol
from openhands.sdk.llm import MessageToolCall

from pyflow import Agent, Model, Session, TestModel, tool
from pyflow.notebook_visualizer import (
    NotebookConversationVisualizer,
    build_notebook_conversation_model,
    notebook_full_markdown_for_session,
    notebook_markdown_for_session,
)


def test_agent_uses_notebook_visualizer_in_jupyter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_visualizer: object | None = None
    fake_conversation = _FakeConversation()

    def conversation_factory(**kwargs: object) -> _FakeConversation:
        nonlocal captured_visualizer
        captured_visualizer = kwargs.get("visualizer")
        return fake_conversation

    monkeypatch.setattr(
        "pyflow.agent.conversation_visualizer_for_environment",
        lambda: NotebookConversationVisualizer(),
    )
    monkeypatch.setattr("pyflow.agent.Conversation", conversation_factory)
    monkeypatch.setattr(
        "pyflow.agent.sync_interactive_session",
        lambda session, **kwargs: None,
    )

    session = "Inspect the notebook renderer." >> Agent(
        model=_test_model_with_finishes("call_finish"),
        tools=(),
    )

    assert session.conversation is fake_conversation
    assert isinstance(captured_visualizer, NotebookConversationVisualizer)


def test_build_notebook_conversation_model_tracks_tool_sections() -> None:
    session = _session_with_rendered_tool_activity()

    model = build_notebook_conversation_model(
        session.events,
        execution_status=session.execution_status,
    )

    assert model.execution_status == "finished"
    assert len(model.turns) >= 2
    assert model.turns[0].role == "user"
    assert model.turns[1].role == "agent"
    assert model.turns[1].messages == []
    assert len(model.turns[1].tool_calls) == 1
    assert model.turns[1].tool_calls[0].tool_name == "session_notebook_sum_tool_test"
    assert [section.title for section in model.turns[1].tool_calls[0].sections] == [
        "Arguments",
        "Reasoning",
        "Result",
    ]
    assert "I will add the numbers." in model.turns[1].tool_calls[0].sections[1].content


def test_notebook_visualizer_renders_live_on_event() -> None:
    display_target = _CaptureWidgetTarget()
    state = _FakeConversationState()
    visualizer = NotebookConversationVisualizer(display_target=display_target)
    visualizer.initialize(cast(ConversationStateProtocol, state))
    session = _session_with_rendered_tool_activity()

    state.execution_status = SimpleNamespace(value="running")
    for event in session.events:
        state.events = tuple([*state.events, event])
        visualizer.on_event(event)

    assert display_target.transcript_calls > 0
    assert display_target.control_calls > 0
    assert all(widget is visualizer.widget for widget in display_target.widgets)
    assert isinstance(visualizer.widget, widgets.VBox)
    assert "## pyflow session" not in display_target.transcripts[-1]
    assert "Status: **Running**" in display_target.transcripts[-1]
    assert "Tool `session_notebook_sum_tool_test`" in display_target.transcripts[-1]
    widget = cast(widgets.VBox, visualizer.widget)
    assert getattr(widget.layout, "display", "") == "none"
    assert not any(
        isinstance(descendant, (widgets.Text, widgets.Textarea))
        for descendant in _flatten_widgets(visualizer.widget)
    )


def test_notebook_live_controls_only_show_for_pending_tool_approval() -> None:
    display_target = _CaptureWidgetTarget()
    state = _FakeConversationState()
    visualizer = NotebookConversationVisualizer(display_target=display_target)
    visualizer.initialize(cast(ConversationStateProtocol, state))
    session = _session_with_rendered_tool_activity()

    pending_events: list[object] = []
    for event in session.events:
        pending_events.append(event)
        if type(event).__name__ == "ActionEvent":
            break

    state.events = tuple(pending_events)
    state.execution_status = SimpleNamespace(value="waiting_for_confirmation")
    visualizer.begin_session_render(start_event_index=0)
    visualizer.refresh()

    widget = cast(widgets.VBox, visualizer.widget)
    assert getattr(widget.layout, "display", "") != "none"
    assert not any(
        isinstance(descendant, (widgets.Text, widgets.Textarea))
        for descendant in _flatten_widgets(visualizer.widget)
    )


def test_notebook_markdown_for_session_is_read_only_transcript() -> None:
    session = _session_with_rendered_tool_activity()

    markdown = notebook_markdown_for_session(session)

    assert "## pyflow session" not in markdown
    assert "Status: **Finished**" in markdown
    assert "### User" in markdown
    assert "### Agent" in markdown
    assert "<details>" in markdown
    assert "Tool `session_notebook_sum_tool_test`" in markdown
    assert "Continue the conversation" not in markdown


def test_session_render_widget_is_read_only() -> None:
    session = _session_with_rendered_tool_activity()

    widget = cast(widgets.VBox, session.render_widget())

    assert isinstance(widget, widgets.VBox)
    assert not any(
        isinstance(descendant, (widgets.Text, widgets.Textarea))
        for descendant in _flatten_widgets(widget)
    )


def test_notebook_full_markdown_includes_system_prompt() -> None:
    session = _session_with_rendered_tool_activity()

    markdown = notebook_full_markdown_for_session(session)

    assert "System Prompt" in markdown
    assert "Tool `session_notebook_sum_tool_test`" in markdown
    assert "Arguments schema:" in markdown
    assert "\"properties\"" in markdown
    assert "Continue the conversation" not in markdown


@dataclass
class _CaptureWidgetTarget:
    transcripts: list[str]
    widgets: list[widgets.Widget]
    transcript_calls: int
    control_calls: int

    def __init__(self) -> None:
        self.transcripts = []
        self.widgets = []
        self.transcript_calls = 0
        self.control_calls = 0

    def begin_live_render(self) -> None:
        return None

    def display_transcript(self, markdown: str) -> None:
        self.transcript_calls += 1
        self.transcripts.append(markdown)

    def display_controls(self, widget: widgets.Widget) -> None:
        self.control_calls += 1
        self.widgets.append(widget)


class _FakeConversation:
    messages: list[str]
    run_calls: int
    state: object

    def __init__(self) -> None:
        self.messages = []
        self.run_calls = 0
        self.state = _FakeConversationState()

    def send_message(self, message: str) -> None:
        self.messages.append(message)

    def run(self) -> None:
        self.run_calls += 1


class _FakeConversationState:
    events: Sequence[object]
    execution_status: object

    def __init__(self) -> None:
        self.events = ()
        self.execution_status = SimpleNamespace(value="finished")


def _session_with_rendered_tool_activity() -> Session:
    model = Model.test(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="I will add the numbers.")],
                tool_calls=[
                    MessageToolCall(
                        id="call_add",
                        name="session_notebook_sum_tool_test",
                        arguments='{"a": 1, "b": 2}',
                        origin="completion",
                    )
                ],
            ),
            _finish_message("call_finish"),
        )
    )
    return "Add 1 and 2." >> Agent(
        model=model,
        tools=(_session_notebook_sum_tool,),
    )


@tool(name="session_notebook_sum_tool_test")
def _session_notebook_sum_tool(a: int, b: int) -> int:
    """Add two numbers for notebook visualization tests."""
    return a + b


def _test_model_with_finishes(*call_ids: str) -> TestModel:
    return Model.test(
        scripted_responses=tuple(_finish_message(call_id) for call_id in call_ids)
    )


def _finish_message(call_id: str, message: str = "Done") -> Message:
    return Message(
        role="assistant",
        content=[TextContent(text="")],
        tool_calls=[
            MessageToolCall(
                id=call_id,
                name="finish",
                arguments=f'{{"message": "{message}"}}',
                origin="completion",
            )
        ],
    )


def _flatten_widgets(widget: widgets.Widget) -> list[widgets.Widget]:
    widgets_found = [widget]
    children = getattr(widget, "children", ())
    for child in children:
        if isinstance(child, widgets.Widget):
            widgets_found.extend(_flatten_widgets(child))
    return widgets_found
