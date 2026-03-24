from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

import pytest
from openhands.sdk import BaseConversation, LLM, Message, TextContent
from openhands.sdk.llm import MessageToolCall
from openhands.sdk.testing import TestLLM
from openhands.sdk.testing import TestLLMExhaustedError
from pydantic import BaseModel
from pydantic import SecretStr
from rich.console import Console

from pyflow import (
    AIModel,
    Agent,
    DisplayEnvironment,
    Model,
    PromptStep,
    Session,
    SessionResultMissingError,
    SessionResultValidationError,
    TestModel,
    code,
    docs,
    output,
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


def test_agent_run_async_returns_session() -> None:
    agent = _agent_with_finishes("run_one")
    request = "Fix the bug." >> tests("unit")

    session = asyncio.run(agent.run_async(request))

    assert isinstance(session, Session)
    assert session.agent is agent


def test_agent_replacing_overrides_selected_fields_only() -> None:
    agent = Agent(
        model=_test_model_with_finishes("run_one"),
        contexts=(docs("plan.md"),),
        tools=(),
        workspace="workspace-a",
    )

    replaced = agent.replacing(workspace="workspace-b")

    assert replaced is not agent
    assert replaced.model is agent.model
    assert replaced.contexts == agent.contexts
    assert replaced.tools == agent.tools
    assert replaced.workspace == "workspace-b"
    assert agent.workspace == "workspace-a"


def test_agent_replacing_supports_multiple_overrides() -> None:
    base_contexts = (docs("plan.md"),)
    updated_contexts = (code("app.py"),)
    base_model = _test_model_with_finishes("base")
    updated_model = _test_model_with_finishes("updated")
    agent = Agent(
        model=base_model,
        contexts=base_contexts,
        tools=(),
        workspace="workspace-a",
    )

    replaced = agent.replacing(
        model=updated_model,
        contexts=updated_contexts,
        tools=(_session_render_sum_tool,),
        workspace="workspace-b",
    )

    assert replaced.model is updated_model
    assert replaced.contexts == updated_contexts
    assert replaced.tools == (_session_render_sum_tool,)
    assert replaced.workspace == "workspace-b"
    assert agent.model is base_model
    assert agent.contexts == base_contexts
    assert agent.tools == ()
    assert agent.workspace == "workspace-a"


def test_step_rshift_agent_and_model_return_session() -> None:
    step = PromptStep(text="Fix the bug.")

    agent_session = step >> _agent_with_finishes("agent_run")
    model_session = step >> _test_model_with_finishes("model_run")

    assert isinstance(agent_session, Session)
    assert isinstance(model_session, Session)


def test_structured_request_rshift_agent_parses_finish_payload() -> None:
    payload = json.dumps({"source": "chunk-a", "row_count": 2})
    model = Model.test(scripted_responses=(_finish_message("run_one", message=payload),))

    session = "Summarize the chunk." // output(_ChunkSummary) >> Agent(model=model, tools=())
    result = session.result

    assert isinstance(result, _ChunkSummary)
    assert result.source == "chunk-a"
    assert result.row_count == 2
    assert session.result is result
    assert session.result_text == payload


def test_structured_request_rshift_model_parses_finish_payload() -> None:
    payload = json.dumps({"source": "chunk-b", "row_count": 4})
    model = Model.test(scripted_responses=(_finish_message("run_one", message=payload),))

    session = "Summarize the chunk." // output(_ChunkSummary) >> model
    result = session.result

    assert isinstance(result, _ChunkSummary)
    assert result.source == "chunk-b"
    assert result.row_count == 4


def test_session_result_returns_raw_finish_message_without_output_contract() -> None:
    session = "Fix the bug." >> _agent_with_finish_messages("raw result")

    assert session.result == "raw result"
    assert session.result_text == "raw result"


@pytest.mark.parametrize(
    ("message", "match"),
    [
        ('{"source": "chunk-a", "row_count": "oops"}', "row_count"),
        ("not json", "Invalid JSON"),
    ],
)
def test_structured_result_validation_errors(
    message: str,
    match: str,
) -> None:
    session = "Summarize the chunk." // output(_ChunkSummary) >> _agent_with_finish_messages(
        message
    )

    with pytest.raises(SessionResultValidationError, match=match) as exc_info:
        _ = session.result

    assert exc_info.value.raw_text == message
    assert exc_info.value.model_type is _ChunkSummary


def test_structured_result_missing_finish_raises_error() -> None:
    model = Model.test(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    session = "Summarize the chunk." // output(_ChunkSummary) >> Agent(model=model, tools=())

    with pytest.raises(SessionResultMissingError, match="finish result"):
        _ = session.result


def test_plain_session_continuation_clears_structured_output_contract() -> None:
    structured_payload = json.dumps({"source": "chunk-a", "row_count": 2})
    agent = Agent(
        model=Model.test(
            scripted_responses=(
                _finish_message("first_run", message=structured_payload),
                _finish_message("second_run", message="follow-up result"),
            )
        ),
        tools=(),
    )
    session = "Summarize the chunk." // output(_ChunkSummary) >> agent

    assert isinstance(session.result, _ChunkSummary)

    returned = "Provide a follow-up." >> session

    assert returned is session
    assert session.output_spec is None
    assert session.result == "follow-up result"


def test_structured_output_is_rejected_for_session_continuation() -> None:
    session = "Start the session." >> _agent_with_finishes("first_run", "second_run")

    with pytest.raises(ValueError, match="fresh runs"):
        _ = "Provide a follow-up." // output(_ChunkSummary) >> session


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


def test_agent_run_async_concurrent_gather_uses_fresh_runtime_models() -> None:
    model = Model.test(scripted_responses=(_finish_message("shared"),))
    agent = Agent(model=model, tools=())
    first_request = "Do the first pass." >> tests("first")
    second_request = "Do the second pass." >> tests("second")

    async def run_both() -> tuple[Session, Session]:
        return await asyncio.gather(
            agent.run_async(first_request),
            agent.run_async(second_request),
        )

    results = asyncio.run(run_both())

    assert all(isinstance(session, Session) for session in results)
    assert [session.agent for session in results] == [agent, agent]
    assert model.llm.call_count == 0


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
    monkeypatch: pytest.MonkeyPatch,
    snapshot_regen: bool,
) -> None:
    session = _session_with_rendered_tool_activity()
    monkeypatch.setattr("pyflow.session._stdout_is_tty", lambda: False)

    assert_snapshot("session_full_transcript", str(session), snapshot_regen)


def test_session_render_stays_compact_and_conversation_focused(
    snapshot_regen: bool,
) -> None:
    session = _session_with_rendered_tool_activity()

    assert_snapshot("session_chat_transcript", session.render(), snapshot_regen)
    assert "System Prompt" not in session.render()


def test_session_render_full_includes_prompt_construction_context(
    snapshot_regen: bool,
) -> None:
    session = _session_with_rendered_tool_activity()

    assert_snapshot("session_full_transcript", session.render_full(), snapshot_regen)
    assert "System Prompt" in session.render_full()
    assert "Tools:" in session.render_full()
    assert "Arguments Schema:" in session.render_full()
    assert "\"properties\"" in session.render_full()


def test_session_exposes_conversation_stats_metrics_and_token_usage() -> None:
    session = "Collect metrics." >> _agent_with_finishes("done")

    assert session.conversation_stats is session.conversation.conversation_stats
    assert session.metrics == session.conversation_stats.get_combined_metrics()
    assert session.token_usage == session.metrics.accumulated_token_usage


def test_session_repr_matches_chat_transcript_in_interactive_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_with_rendered_tool_activity()
    monkeypatch.setattr(
        "pyflow.session.detect_display_environment",
        lambda: DisplayEnvironment.PYTHON_REPL,
    )

    assert repr(session) == session.render_full()


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
    monkeypatch.setattr(
        "pyflow.display._sync_notebook_session",
        lambda session, **kwargs: None,
    )
    monkeypatch.setattr(
        "pyflow.session.detect_display_environment",
        lambda: DisplayEnvironment.JUPYTER,
    )
    monkeypatch.setattr(
        "pyflow.display._current_notebook_cell_will_display_expression",
        lambda: True,
    )
    sync_interactive_session(session, start_event_index=0)

    suppressed = session._repr_mimebundle_()
    assert should_suppress_notebook_display(session)
    _clear_pending_notebook_values()
    displayed = session._repr_mimebundle_()

    assert suppressed == {}
    assert displayed["text/plain"] == session.render_full()
    assert displayed["text/markdown"] == session.render_full_markdown()


def test_session_transcript_renders_pending_tool_call_without_html() -> None:
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

    text = transcript.render_text()

    assert "Tool Call: terminal" in text
    assert "Arguments:" in text
    assert "pytest" in text


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


def test_model_from_api_allows_missing_api_key() -> None:
    model = Model.from_api(
        name="local/model",
        base_url="http://localhost:11434/v1",
    )

    assert isinstance(model, AIModel)
    assert model.llm.model == "local/model"
    assert model.llm.base_url == "http://localhost:11434/v1"
    assert model.llm.api_key is None


def test_model_from_api_rejects_tool_choice_configuration() -> None:
    with pytest.raises(ValueError, match="tool_choice='required'") as exc_info:
        Model.from_api(
            name="openai/gpt-4.1",
            api_key=SecretStr("test-key"),
            tool_choice="required",
        )

    assert "does not support configuring `tool_choice`" in str(exc_info.value)


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
    openhands_agent = agent._build_openhands_agent(runtime_model=model, interactive=True)

    assert isinstance(openhands_agent.llm, TestLLM)
    assert openhands_agent.llm is model.llm
    assert openhands_agent.system_prompt_kwargs["cli_mode"] is True


def test_agent_builds_noninteractive_openhands_agent_for_background_runs() -> None:
    model = Model.test(
        scripted_responses=(
            Message(role="assistant", content=[TextContent(text="Done")]),
        )
    )
    agent = Agent(model=model, tools=())

    openhands_agent = agent._build_openhands_agent(runtime_model=model, interactive=False)

    assert isinstance(openhands_agent.llm, TestLLM)
    assert openhands_agent.llm is model.llm
    assert openhands_agent.system_prompt_kwargs["cli_mode"] is False


def test_agent_rejects_models_without_native_tool_calling_support() -> None:
    llm = LLM(model="provider/no-tools", api_key=SecretStr("test-key"))
    llm._model_info = {"supports_function_calling": False}
    model = AIModel(llm=llm)
    agent = Agent(model=model)

    with pytest.raises(ValueError, match="does not support function/tool calls"):
        agent._build_openhands_agent(runtime_model=model)


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


def _agent_with_finish_messages(*messages: str) -> Agent:
    return Agent(
        model=Model.test(
            scripted_responses=tuple(
                _finish_message(f"run_{index}", message=message)
                for index, message in enumerate(messages, start=1)
            )
        ),
        tools=(),
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
                arguments=json.dumps({"message": message}),
                origin="completion",
            )
        ],
    )


class _ChunkSummary(BaseModel):
    source: str
    row_count: int
