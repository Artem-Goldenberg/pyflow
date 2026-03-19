from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Sequence, cast

import ipywidgets as widgets
import pytest
from openhands.sdk.conversation.base import ConversationStateProtocol
from openhands.sdk.llm import Message, MessageToolCall, TextContent

from pyflow import Agent, Session, TestModel, tool
from pyflow.notebook_visualizer import (
    NotebookConversationVisualizer,
    build_notebook_conversation_model,
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
    monkeypatch.setattr("pyflow.agent.sync_interactive_session", lambda session: None)

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


def test_notebook_visualizer_updates_widget_live() -> None:
    display_target = _CaptureWidgetTarget()
    state = _FakeConversationState()
    visualizer = NotebookConversationVisualizer(display_target=display_target)
    visualizer.initialize(cast(ConversationStateProtocol, state))
    session = _session_with_rendered_tool_activity()

    state.execution_status = SimpleNamespace(value="running")
    for event in session.events:
        state.events = tuple([*state.events, event])
        visualizer.on_event(event)

    state.execution_status = SimpleNamespace(value="finished")
    visualizer.refresh()

    assert display_target.display_calls == len(session.events) + 1
    assert all(widget is visualizer.widget for widget in display_target.widgets)
    assert isinstance(visualizer.widget, widgets.VBox)

    header = cast(widgets.HBox, visualizer.widget.children[1])
    title = cast(widgets.HTML, header.children[0])
    status = cast(widgets.HTML, header.children[1])

    assert "Conversation Transcript" in title.value
    assert "Finished" in status.value


@dataclass
class _CaptureWidgetTarget:
    widgets: list[widgets.Widget]
    display_calls: int

    def __init__(self) -> None:
        self.widgets = []
        self.display_calls = 0

    def display(self, widget: widgets.Widget) -> None:
        self.display_calls += 1
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
    model = TestModel(
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
    return TestModel(
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
