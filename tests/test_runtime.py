from __future__ import annotations

import io
import pytest
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

from openhands.sdk import LLM
from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.testing import TestLLM
from openhands.sdk.testing import TestLLMExhaustedError
from pydantic import SecretStr
from rich.console import Console

from pyflow import (
    AIModel,
    Agent,
    DisplayEnvironment,
    Model,
    PromptStep,
    Session,
    TestModel,
    code,
    docs,
    tests,
    tool,
)
from pyflow.display import (
    _clear_pending_notebook_values,
    should_suppress_notebook_display,
    sync_interactive_session,
)
from pyflow.session_rendering import SessionToolCall, SessionTranscript, SessionTurn
from pyflow.sink import RequestInput


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_step_rshift_sink_uses_rrshift() -> None:
    sink = CaptureSink()
    step = PromptStep(text="Fix the bug.")

    result = step >> sink

    assert result is sink.result
    assert isinstance(sink.last_input, PromptStep)


def test_request_rshift_sink_uses_rrshift() -> None:
    sink = CaptureSink()
    request = "Fix the bug." >> tests("unit")

    result = request >> sink

    assert result is sink.result
    assert sink.last_input is request


def test_request_rshift_agent_returns_session() -> None:
    agent = _agent_with_finishes("run_one")

    session = "Fix the bug." >> agent

    assert isinstance(session, Session)
    assert session.agent is agent


def test_request_rshift_model_returns_session() -> None:
    model = _test_model_with_finishes("run_one")

    session = "Fix the bug." >> model

    assert isinstance(session, Session)


def test_step_rshift_agent_and_model_return_session() -> None:
    step = PromptStep(text="Fix the bug.")

    agent_session = step >> _agent_with_finishes("agent_run")
    model_session = step >> _test_model_with_finishes("model_run")

    assert isinstance(agent_session, Session)
    assert isinstance(model_session, Session)


def test_request_rshift_session_reuses_same_session() -> None:
    agent = _agent_with_finishes("first_run", "second_run")
    session = "Inspect the parser design." >> agent

    returned = "Now refactor only the tokenizer part." >> session

    assert returned is session
    assert returned.conversation is session.conversation


def test_step_rshift_session_coerces_through_continuation_path() -> None:
    agent = _agent_with_finishes("first_run", "second_run")
    session = "Inspect the parser design." >> agent

    returned = PromptStep(text="Now refactor only the tokenizer part.") >> session

    assert returned is session
    assert returned.conversation is session.conversation


def test_session_continuation_does_not_build_fresh_llm() -> None:
    model = CountingModel(
        scripted_responses=(
            _finish_message("first_run"),
            _finish_message("second_run"),
        )
    )
    agent = Agent(model=model, tools=())

    session = "Do the first pass." >> agent
    _ = "Do the second pass." >> session

    assert isinstance(session, Session)
    assert model.build_llm_calls == 1


def test_session_continuation_appends_plain_request_without_global_context() -> None:
    agent = Agent(
        model=_test_model_with_finishes("unused"),
        contexts=(docs("plan.md"),),
    )
    conversation = CaptureConversation()
    session = Session(
        agent=agent,
        conversation=cast(BaseConversation, conversation),
    )

    returned = "Follow up change." >> session

    assert returned is session
    assert conversation.messages == ["1. Follow up change."]
    assert conversation.run_calls == 1


def test_session_str_renders_chat_transcript_with_tool_activity(
    snapshot_regen: bool,
) -> None:
    session = _session_with_rendered_tool_activity()

    assert_snapshot("session_chat_transcript", str(session), snapshot_regen)


def test_session_repr_matches_chat_transcript_in_interactive_mode(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_regen: bool,
) -> None:
    session = _session_with_rendered_tool_activity()
    monkeypatch.setattr(
        "pyflow.session.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )

    assert_snapshot("session_chat_transcript", repr(session), snapshot_regen)


def test_session_repr_uses_python_object_style_in_common_cli() -> None:
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())
    session = Session(
        agent=agent,
        conversation=cast(BaseConversation, CaptureConversation()),
    )

    assert repr(session).startswith("Session(agent=Agent(")
    assert "conversation=CaptureConversation()" in repr(session)


def test_session_rich_rendering_uses_snapshot(snapshot_regen: bool) -> None:
    session = _session_with_rendered_tool_activity()
    console = Console(record=True, width=100, file=io.StringIO())

    console.print(session)

    assert_snapshot(
        "session_rich_transcript",
        console.export_text(),
        snapshot_regen,
    )


def test_session_html_rendering_uses_snapshot(snapshot_regen: bool) -> None:
    session = _session_with_rendered_tool_activity()

    assert_snapshot(
        "session_html_transcript",
        session.render_html(),
        snapshot_regen,
    )


def test_session_repr_html_matches_html_rendering(snapshot_regen: bool) -> None:
    session = _session_with_rendered_tool_activity()

    assert_snapshot(
        "session_html_transcript",
        session._repr_html_(),
        snapshot_regen,
    )


def test_session_repr_mimebundle_suppresses_immediate_notebook_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_with_rendered_tool_activity()
    shell = _FakeNotebookShell()

    monkeypatch.setattr(
        "pyflow.display.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr("pyflow.display._get_ipython_shell", lambda: shell)
    monkeypatch.setattr("pyflow.display._sync_notebook_session", lambda session: None)
    monkeypatch.setattr(
        "pyflow.session.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr(
        "pyflow.display._current_notebook_cell_will_display_expression",
        lambda: True,
    )
    sync_interactive_session(session)

    suppressed = session._repr_mimebundle_()
    suppressed_html = session._repr_html_()
    assert should_suppress_notebook_display(session)
    _clear_pending_notebook_values()
    displayed = session._repr_mimebundle_()

    assert suppressed == {}
    assert suppressed_html == ""
    assert displayed["text/plain"] == session.render()
    assert "application/vnd.jupyter.widget-view+json" in displayed


def test_session_html_shows_pending_confirmation_banner() -> None:
    transcript = SessionTranscript(
        turns=(
            SessionTurn(
                role="agent",
                tool_calls=[
                    SessionToolCall(
                        tool_name="terminal",
                        tool_call_id="call_terminal",
                        arguments='{"command": "pytest"}',
                    )
                ],
            ),
        ),
        execution_status="waiting_for_confirmation",
    )

    html = transcript.render_html()

    assert "Approval required" in html
    assert "session.approve_pending_actions()" in html
    assert "terminal" in html


def test_ai_model_build_llm_maps_fields() -> None:
    model = AIModel(
        name="openai/gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("test-key"),
    )

    llm = model.build_llm()

    assert llm.model == "openai/gpt-4.1"
    assert llm.base_url == "https://api.openai.com/v1"
    assert isinstance(llm.api_key, SecretStr)
    assert llm.api_key.get_secret_value() == "test-key"


def test_test_model_build_llm_uses_scripted_responses() -> None:
    scripted = (
        Message(role="assistant", content=[TextContent(text="First")]),
        RuntimeError("boom"),
    )
    model = TestModel(scripted_responses=scripted, name="scripted-test")
    llm = model.build_llm()
    user_message = Message(role="user", content=[TextContent(text="Hi")])

    first = llm.completion([user_message])

    assert isinstance(llm, TestLLM)
    assert llm.model == "scripted-test"
    assert _content_as_text(first.message) == "First"
    assert llm.call_count == 1

    with pytest.raises(RuntimeError, match="boom"):
        llm.completion([user_message])

    assert llm.call_count == 2
    assert llm.remaining_responses == 0

    with pytest.raises(TestLLMExhaustedError):
        llm.completion([user_message])


def test_agent_builds_openhands_agent_with_test_model_llm() -> None:
    model = TestModel(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    # This test verifies LLM wiring, not built-in tool wiring.
    agent = Agent(model=model, tools=())
    openhands_agent = agent._build_openhands_agent()

    assert isinstance(openhands_agent.llm, TestLLM)


def test_agent_render_message_with_context(snapshot_regen: bool) -> None:
    model = TestModel(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    agent = Agent(model=model, contexts=(docs("plan.md"), code("app.py")))
    request = "Refactor the module." >> tests("unit")

    rendered = agent._render_message(request)

    assert_snapshot("agent_render_message_with_context", rendered, snapshot_regen)


def test_agent_workspace_defaults_to_cwd() -> None:
    model = TestModel(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    agent = Agent(model=model)

    assert agent.workspace == Path.cwd()


@dataclass(frozen=True, kw_only=True)
class CountingModel(Model):
    scripted_responses: Sequence[Message | Exception]
    name: str = "counting-test-model"
    build_llm_calls: int = 0

    def build_llm(self) -> LLM:
        object.__setattr__(self, "build_llm_calls", self.build_llm_calls + 1)
        return TestLLM.from_messages(
            messages=list(self.scripted_responses),
            model=self.name,
        )


class CaptureSink:
    result: Session
    last_input: RequestInput | None

    def __init__(self) -> None:
        self.result = cast(Session, object())
        self.last_input = None

    def __rrshift__(self, lhs: RequestInput) -> Session:
        self.last_input = lhs
        return self.result


class CaptureConversation:
    messages: list[str]
    run_calls: int

    def __init__(self) -> None:
        self.messages = []
        self.run_calls = 0

    def send_message(self, text: str) -> None:
        self.messages.append(text)

    def run(self) -> None:
        self.run_calls += 1

    def __repr__(self) -> str:
        return "CaptureConversation()"


def assert_snapshot(name: str, content: str, regen: bool) -> None:
    path = FIXTURES_DIR / f"{name}.txt"
    if regen:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert content.rstrip("\n") == expected.rstrip("\n")


def _content_as_text(message: Message) -> str:
    parts: list[str] = []
    for item in message.content:
        if isinstance(item, TextContent):
            parts.append(item.text)
    return "\n".join(parts)


class _FakeNotebookShell:
    execution_count: int

    def __init__(self) -> None:
        self.execution_count = 1


def _test_model_with_finishes(*call_ids: str) -> TestModel:
    return TestModel(scripted_responses=tuple(_finish_message(call_id) for call_id in call_ids))


def _agent_with_finishes(*call_ids: str) -> Agent:
    # Most runtime tests do not exercise built-in OpenHands tools. Using no tools
    # avoids terminal bootstrap overhead in each Conversation.run() call.
    return Agent(model=_test_model_with_finishes(*call_ids), tools=())


def _session_with_rendered_tool_activity() -> Session:
    model = TestModel(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="I will add the numbers.")],
                tool_calls=[
                    MessageToolCall(
                        id="call_add",
                        name="session_render_sum_tool_test",
                        arguments='{"a": 1, "b": 2}',
                        origin="completion",
                    )
                ],
            ),
            _finish_message("call_finish"),
        )
    )
    return "Add 1 and 2." >> Agent(model=model, tools=(_session_render_sum_tool,))


@tool(name="session_render_sum_tool_test")
def _session_render_sum_tool(a: int, b: int) -> int:
    """Add two numbers for transcript rendering."""
    return a + b


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
