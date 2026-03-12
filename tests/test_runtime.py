from __future__ import annotations

import pytest
from pathlib import Path
from typing import cast

from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.testing import TestLLM
from openhands.sdk.testing import TestLLMExhaustedError
from pydantic import SecretStr

from pyflow import AIModel, Agent, PromptStep, Request, TestModel, code, docs, tests
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
    agent = Agent(model=model)
    request = Request(steps=(PromptStep(text="Run the task."),))
    openhands_agent = agent._build_openhands_agent(request)

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


def assert_snapshot(name: str, content: str, regen: bool) -> None:
    path = FIXTURES_DIR / f"{name}.txt"
    if regen:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert content == expected


def _content_as_text(message: Message) -> str:
    parts: list[str] = []
    for item in message.content:
        if isinstance(item, TextContent):
            parts.append(item.text)
    return "\n".join(parts)


class CaptureSink:
    result: BaseConversation
    last_input: RequestInput | None

    def __init__(self) -> None:
        self.result = cast(BaseConversation, object())
        self.last_input = None

    def __rrshift__(self, lhs: RequestInput) -> BaseConversation:
        self.last_input = lhs
        return self.result
