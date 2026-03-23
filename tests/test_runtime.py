from __future__ import annotations

import io
import pytest
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

from openhands.sdk import BaseConversation, LLM, Message, TextContent
from openhands.sdk.llm import MessageToolCall
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


def test_two_fresh_runs_share_same_owned_llm() -> None:
    model = Model.test(
        scripted_responses=(
            _finish_message("first_run"),
            _finish_message("second_run"),
        )
    )

    first = "Do the first pass." >> model
    second = "Do the second pass." >> model

    assert isinstance(first, Session)
    assert isinstance(second, Session)
    assert first.agent.model.inner_llm is model.llm
    assert second.agent.model.inner_llm is model.llm
    assert model.llm.call_count == 2


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
    assert displayed["text/markdown"] == session.render_markdown()


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


def test_model_from_api_returns_ai_model_and_maps_llm_fields() -> None:
    model = Model.from_api(
        name="openai/gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("test-key"),
        max_input_tokens=20000,
        max_output_tokens=567,
        temperature=0.25,
    )

    assert isinstance(model, AIModel)
    assert model.llm.model == "openai/gpt-4.1"
    assert model.llm.base_url == "https://api.openai.com/v1"
    assert isinstance(model.llm.api_key, SecretStr)
    assert model.llm.api_key.get_secret_value() == "test-key"
    assert model.llm.max_input_tokens == 20000
    assert model.llm.max_output_tokens == 567
    assert model.llm.temperature == 0.25
    assert model.llm.log_completions is True
    assert model.llm.log_completions_folder == "logs/completions"


def test_ai_model_direct_wrapper_preserves_llm_identity() -> None:
    llm = LLM(model="openai/gpt-4.1", api_key=SecretStr("test-key"))
    model = AIModel(llm=llm)

    assert model.llm is llm


def test_model_subscription_returns_ai_model_and_calls_openhands_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_llm = LLM(model="openai/gpt-5.2-codex", api_key=SecretStr("unused"))
    captured: dict[str, object] = {}

    def fake_subscription_login(
        *,
        vendor: str,
        model: str,
        force_login: bool,
        open_browser: bool,
        skip_consent: bool,
        **kwargs: object,
    ) -> LLM:
        captured.update(
            vendor=vendor,
            model=model,
            force_login=force_login,
            open_browser=open_browser,
            skip_consent=skip_consent,
            **kwargs,
        )
        return sentinel_llm

    monkeypatch.setattr("pyflow.model.LLM.subscription_login", fake_subscription_login)

    model = Model.subscription(
        vendor="openai",
        model="gpt-5.2-codex",
        force_login=True,
        open_browser=False,
        skip_consent=True,
        max_input_tokens=4096,
        max_output_tokens=1024,
        temperature=0.5,
    )

    assert isinstance(model, AIModel)
    assert model.llm is sentinel_llm
    assert captured == {
        "vendor": "openai",
        "model": "gpt-5.2-codex",
        "force_login": True,
        "open_browser": False,
        "skip_consent": True,
        "max_input_tokens": 4096,
        "max_output_tokens": 1024,
        "temperature": 0.5,
        "log_completions": True,
        "log_completions_folder": "logs/completions",
        "prompt_cache_retention": None,
    }


def test_model_test_returns_test_model_with_stable_scripted_responses() -> None:
    scripted = (
        Message(role="assistant", content=[TextContent(text="First")]),
        RuntimeError("boom"),
    )
    model = Model.test(
        scripted_responses=scripted,
        name="scripted-test",
        max_output_tokens=321,
    )
    user_message = Message(role="user", content=[TextContent(text="Hi")])

    first = model.llm.completion([user_message])

    assert isinstance(model, TestModel)
    assert isinstance(model.llm, TestLLM)
    assert model.llm.model == "scripted-test"
    assert model.llm.max_output_tokens == 321
    assert model.scripted_responses == scripted
    assert _content_as_text(first.message) == "First"
    assert model.llm.call_count == 1

    with pytest.raises(RuntimeError, match="boom"):
        model.llm.completion([user_message])

    assert model.llm.call_count == 2
    assert model.llm.remaining_responses == 0
    assert model.scripted_responses == scripted

    with pytest.raises(TestLLMExhaustedError):
        model.llm.completion([user_message])


def test_test_model_direct_wrapper_preserves_llm_and_scripted_responses() -> None:
    scripted = (
        Message(role="assistant", content=[TextContent(text="First")]),
        RuntimeError("boom"),
    )
    llm = TestLLM.from_messages(messages=list(scripted), model="scripted-test")
    model = TestModel(llm=llm, scripted_responses=scripted)

    assert model.llm is llm
    assert model.scripted_responses == scripted


def test_agent_builds_openhands_agent_with_test_model_llm() -> None:
    model = Model.test(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    # This test verifies LLM wiring, not built-in tool wiring.
    agent = Agent(model=model, tools=())
    openhands_agent = agent._build_openhands_agent(runtime_model=model)

    assert isinstance(openhands_agent.llm, TestLLM)
    assert openhands_agent.llm is model.llm


def test_agent_render_message_with_context(snapshot_regen: bool) -> None:
    model = Model.test(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    agent = Agent(model=model, contexts=(docs("plan.md"), code("app.py")))
    request = "Refactor the module." >> tests("unit")

    rendered = agent._render_message(request)

    assert_snapshot("agent_render_message_with_context", rendered, snapshot_regen)


def test_agent_workspace_defaults_to_cwd() -> None:
    model = Model.test(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    agent = Agent(model=model)

    assert agent.workspace == Path.cwd()


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
    return Model.test(
        scripted_responses=tuple(_finish_message(call_id) for call_id in call_ids)
    )


def _agent_with_finishes(*call_ids: str) -> Agent:
    # Most runtime tests do not exercise built-in OpenHands tools. Using no tools
    # avoids terminal bootstrap overhead in each Conversation.run() call.
    return Agent(model=_test_model_with_finishes(*call_ids), tools=())


def _session_with_rendered_tool_activity() -> Session:
    model = Model.test(
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
