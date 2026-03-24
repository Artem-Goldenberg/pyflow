from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import cast, Sequence

import pytest
from openhands.sdk import BaseConversation, LLM, Message, TextContent
from openhands.sdk.llm import MessageToolCall
from pydantic import BaseModel
from pydantic import SecretStr

from pyflow import (
    AIModel,
    Agent,
    Model,
    ParallelFailure,
    Request,
    Session,
    TestModel,
    output,
)


def test_ai_model_fresh_runtime_model_clones_llm_and_resets_metrics() -> None:
    llm = LLM(
        model="openai/gpt-4.1",
        api_key=SecretStr("test-key"),
        stream=True,
    )
    model = AIModel(llm=llm)
    _ = model.llm.metrics

    fresh = model._fresh_runtime_model()

    assert isinstance(fresh, AIModel)
    assert fresh is not model
    assert fresh.llm is not llm
    assert fresh.llm.stream is True
    assert fresh.llm.metrics is not llm.metrics
    assert fresh.llm._telemetry is not llm._telemetry


def test_ai_model_fresh_runtime_model_preserves_subscription_mode() -> None:
    llm = LLM(
        model="openai/gpt-5.2-codex",
        api_key=SecretStr("test-key"),
        base_url="https://chatgpt.com/backend-api/codex",
        stream=True,
    )
    llm._is_subscription = True
    model = AIModel(llm=llm)

    fresh = model._fresh_runtime_model()

    assert fresh.llm is not llm
    assert fresh.llm.is_subscription is True
    assert fresh.llm.stream is True
    assert fresh.llm._telemetry is not llm._telemetry


def test_test_model_fresh_runtime_model_replays_scripted_responses() -> None:
    model = Model.test(
        scripted_responses=(_assistant_message("Done"),),
        max_output_tokens=321,
    )
    prompt = [Message(role="user", content=[TextContent(text="Hi")])]

    first = model._fresh_runtime_model()
    second = model._fresh_runtime_model()
    first_response = first.llm.completion(prompt)
    second_response = second.llm.completion(prompt)

    assert isinstance(first, TestModel)
    assert first.llm is not model.llm
    assert first.llm.max_output_tokens == 321
    assert _message_text(first_response.message) == "Done"
    assert _message_text(second_response.message) == "Done"
    assert model.llm.call_count == 0


def test_parallel_returns_sessions_in_input_order_even_if_workers_finish_out_of_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _RunTracker(delays={"slow": 0.08, "medium": 0.03, "fast": 0.0})
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    def fake_prepare_session(
        self: Agent,
        request: Request,
        *,
        runtime_model: object,
        interactive: bool,
    ) -> Session:
        del runtime_model, interactive
        label = _request_label(request)
        conversation = _TrackingConversation(label=label, tracker=tracker)
        return Session(agent=self, conversation=cast(BaseConversation, conversation))

    monkeypatch.setattr(Agent, "_prepare_session", fake_prepare_session)

    results = agent.parallel(
        ["slow", "fast", "medium"],
        lambda item: item,
    )

    assert all(isinstance(result, Session) for result in results)
    assert tracker.completed == ["fast", "medium", "slow"]
    assert [_conversation_label(cast(Session, result)) for result in results] == [
        "slow",
        "fast",
        "medium",
    ]


@pytest.mark.parametrize("max_concurrency", [0, -1])
def test_parallel_rejects_non_positive_max_concurrency(max_concurrency: int) -> None:
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    with pytest.raises(ValueError, match="max_concurrency"):
        agent.parallel([], lambda item: str(item), max_concurrency=max_concurrency)


def test_parallel_empty_input_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    def fail_prepare_session(
        self: Agent,
        request: Request,
        *,
        runtime_model: object,
        interactive: bool,
    ) -> Session:
        del self, request, runtime_model, interactive
        raise AssertionError("_prepare_session should not be called for empty input.")

    monkeypatch.setattr(Agent, "_prepare_session", fail_prepare_session)

    assert agent.parallel([], lambda item: str(item)) == []


def test_parallel_returns_inline_build_request_failures() -> None:
    agent = Agent(model=_test_model_with_finishes("run_one"), tools=())

    def build_request(item: str) -> str:
        if item == "bad":
            raise RuntimeError("boom")
        return item

    results = agent.parallel(["good", "bad"], build_request)

    assert isinstance(results[0], Session)
    assert isinstance(results[1], ParallelFailure)
    assert results[1].index == 1
    assert results[1].item == "bad"
    assert results[1].phase == "build_request"
    assert results[1].session is None
    assert str(results[1].error) == "boom"


def test_parallel_returns_inline_runtime_failures_with_partial_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _RunTracker(failing_labels=("bad",))
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    def fake_prepare_session(
        self: Agent,
        request: Request,
        *,
        runtime_model: object,
        interactive: bool,
    ) -> Session:
        del runtime_model, interactive
        label = _request_label(request)
        conversation = _TrackingConversation(label=label, tracker=tracker)
        return Session(agent=self, conversation=cast(BaseConversation, conversation))

    monkeypatch.setattr(Agent, "_prepare_session", fake_prepare_session)

    results = agent.parallel(["ok", "bad"], lambda item: item)

    assert isinstance(results[0], Session)
    assert isinstance(results[1], ParallelFailure)
    assert results[1].index == 1
    assert results[1].item == "bad"
    assert results[1].phase == "run"
    assert results[1].session is not None
    assert str(results[1].error) == "boom: bad"


def test_parallel_limits_worker_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _RunTracker(block_until_started=2, delays={str(index): 0.01 for index in range(4)})
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    def fake_prepare_session(
        self: Agent,
        request: Request,
        *,
        runtime_model: object,
        interactive: bool,
    ) -> Session:
        del runtime_model, interactive
        label = _request_label(request)
        conversation = _TrackingConversation(label=label, tracker=tracker)
        return Session(agent=self, conversation=cast(BaseConversation, conversation))

    monkeypatch.setattr(Agent, "_prepare_session", fake_prepare_session)

    results = agent.parallel(
        [0, 1, 2, 3],
        lambda item: str(item),
        max_concurrency=2,
    )

    assert all(isinstance(result, Session) for result in results)
    assert tracker.max_active == 2


def test_parallel_does_not_use_interactive_display_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(model=_test_model_with_finishes("unused"), tools=())

    def fail_visualizer() -> None:
        raise AssertionError("conversation_visualizer_for_environment() should not be called.")

    def fail_sync(session: Session) -> None:
        del session
        raise AssertionError("sync_interactive_session() should not be called.")

    monkeypatch.setattr("pyflow.agent.conversation_visualizer_for_environment", fail_visualizer)
    monkeypatch.setattr("pyflow.agent.sync_interactive_session", fail_sync)
    monkeypatch.setattr("pyflow.agent.Conversation", _InstantConversation)
    monkeypatch.setattr(
        Agent,
        "_build_openhands_agent",
        lambda self, *, runtime_model, interactive: object(),
    )

    results = agent.parallel(["one"], lambda item: item)

    assert len(results) == 1
    assert isinstance(results[0], Session)


def test_parallel_with_test_model_uses_fresh_worker_models() -> None:
    model = Model.test(scripted_responses=(_finish_message("shared"),))
    agent = Agent(model=model, tools=())

    results = agent.parallel(["one", "two", "three"], lambda item: item)

    assert all(isinstance(result, Session) for result in results)
    assert model.llm.call_count == 0
    assert [cast(Session, result).agent for result in results] == [agent, agent, agent]


def test_parallel_sessions_preserve_structured_output_contract() -> None:
    payload = json.dumps({"label": "ok"})
    model = Model.test(scripted_responses=(_finish_message("shared", message=payload),))
    agent = Agent(model=model, tools=())

    results = agent.parallel(
        ["one", "two"],
        lambda item: f"Summarize {item}" // output(_ParallelSummary),
    )

    assert all(isinstance(result, Session) for result in results)
    assert [cast(Session, result).result_text for result in results] == [payload, payload]
    assert [cast(_ParallelSummary, cast(Session, result).result).label for result in results] == [
        "ok",
        "ok",
    ]


def _assistant_message(text: str) -> Message:
    return Message(role="assistant", content=[TextContent(text=text)])


def _conversation_label(session: Session) -> str:
    conversation = cast(_TrackingConversation, session.conversation)
    return conversation.label


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


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for item in message.content:
        if isinstance(item, TextContent):
            parts.append(item.text)
    return "\n".join(parts)


class _ParallelSummary(BaseModel):
    label: str


def _request_label(request: Request) -> str:
    return request.steps[0].render_base()


def _test_model_with_finishes(*call_ids: str) -> TestModel:
    return Model.test(
        scripted_responses=tuple(_finish_message(call_id) for call_id in call_ids)
    )


@dataclass
class _RunTracker:
    delays: dict[str, float] | None = None
    block_until_started: int = 0
    failing_labels: Sequence[str] = ()
    condition: threading.Condition = field(init=False, repr=False)
    started: int = field(init=False, default=0)
    active: int = field(init=False, default=0)
    max_active: int = field(init=False, default=0)
    completed: list[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.condition = threading.Condition()


class _TrackingConversation:
    label: str
    messages: list[str]
    run_calls: int
    tracker: _RunTracker

    def __init__(self, *, label: str, tracker: _RunTracker) -> None:
        self.label = label
        self.messages = []
        self.run_calls = 0
        self.tracker = tracker

    def send_message(self, text: str) -> None:
        self.messages.append(text)

    def run(self) -> None:
        self.run_calls += 1
        with self.tracker.condition:
            self.tracker.started += 1
            self.tracker.active += 1
            self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
            self.tracker.condition.notify_all()
            if self.tracker.block_until_started > 0:
                self.tracker.condition.wait_for(
                    lambda: self.tracker.started >= self.tracker.block_until_started,
                    timeout=1.0,
                )
            delay = (
                0.0
                if self.tracker.delays is None
                else self.tracker.delays.get(self.label, 0.0)
            )

        try:
            if delay > 0.0:
                time.sleep(delay)
            if self.label in self.tracker.failing_labels:
                raise RuntimeError(f"boom: {self.label}")
            with self.tracker.condition:
                self.tracker.completed.append(self.label)
        finally:
            with self.tracker.condition:
                self.tracker.active -= 1
                self.tracker.condition.notify_all()

    def __repr__(self) -> str:
        return f"_TrackingConversation(label={self.label!r})"


class _InstantConversation:
    messages: list[str]
    run_calls: int

    def __init__(self, **kwargs: object) -> None:
        assert kwargs.get("visualizer") is None
        self.messages = []
        self.run_calls = 0

    def send_message(self, text: str) -> None:
        self.messages.append(text)

    def run(self) -> None:
        self.run_calls += 1

    def __repr__(self) -> str:
        return "_InstantConversation()"
