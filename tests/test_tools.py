from __future__ import annotations

import pytest
from typing import Any, cast

from openhands.sdk import Observation
from openhands.sdk.event import ActionEvent, ObservationEvent
from openhands.sdk.llm import Message, MessageToolCall, TextContent

from pyflow import (
    Agent,
    FunctionTool,
    PromptStep,
    Request,
    Session,
    TestModel,
    ToolSet,
    apply_patch_tool,
    read_file_tool,
    terminal_tool,
    tool,
)
from pyflow.tooling import compile_openhands_tools


def test_tool_base_supports_leaf_and_toolset_rendering() -> None:
    @tool(name="render_alpha_tool_test")
    def render_alpha(text: str) -> str:
        """Render alpha."""
        return text

    @tool(name="render_beta_tool_test")
    def render_beta(text: str) -> str:
        """Render beta."""
        return text

    assert terminal_tool.render() == "Use tool: terminal."
    assert render_alpha.render() == "Use tool: render_alpha_tool_test."
    assert tool.use("render_alpha_tool_test", "render_beta_tool_test").render() == (
        "Use tools: render_alpha_tool_test, render_beta_tool_test."
    )


def test_builtin_openhands_tools_are_wrapped_as_function_tools() -> None:
    assert isinstance(terminal_tool, FunctionTool)
    assert isinstance(read_file_tool, FunctionTool)
    assert isinstance(apply_patch_tool, FunctionTool)


def test_tool_factory_supports_lookup_and_decorator_usage() -> None:
    @tool(name="count_letters_tool_test")
    def count_letters(text: str) -> int:
        """Count the number of characters in the input."""
        return len(text)

    looked_up = tool("count_letters_tool_test")

    assert looked_up is count_letters
    assert isinstance(count_letters, FunctionTool)
    assert count_letters.name == "count_letters_tool_test"


def test_tool_use_flattens_nested_toolsets() -> None:
    @tool(name="toolset_one_tool_test")
    def first(value: str) -> str:
        """First tool."""
        return value

    @tool(name="toolset_two_tool_test")
    def second(value: str) -> str:
        """Second tool."""
        return value

    @tool(name="toolset_three_tool_test")
    def third(value: str) -> str:
        """Third tool."""
        return value

    combined = tool.use(
        "toolset_one_tool_test",
        tool.use("toolset_two_tool_test", "toolset_three_tool_test"),
    )

    assert isinstance(combined, ToolSet)
    assert combined.render() == (
        "Use tools: toolset_one_tool_test, toolset_two_tool_test, toolset_three_tool_test."
    )


def test_function_tool_maps_docstring_and_signature_to_schema() -> None:
    @tool(name="schema_mapping_tool_test")
    def repeat_text(text: str, count: int = 3, enabled: bool = True) -> list[str]:
        """Repeat text into a list of strings."""
        if not enabled:
            return []
        return [text] * count

    action_fields = repeat_text.action_type.model_fields
    observation_fields = repeat_text.observation_type.model_fields

    assert repeat_text.description == "Repeat text into a list of strings."
    assert action_fields["text"].annotation is str
    assert action_fields["count"].annotation is int
    assert action_fields["count"].default == 3
    assert action_fields["enabled"].default is True
    assert observation_fields["result"].annotation == list[str]


def test_function_tool_uses_observation_return_annotation_directly() -> None:
    @tool(name="echo_observation_tool_test")
    def echo_text(text: str) -> _EchoObservation:
        """Return a typed observation."""
        return _EchoObservation(
            echoed=text,
            content=[TextContent(text=text)],
        )

    assert echo_text.observation_type is _EchoObservation


def test_function_tool_rejects_missing_parameter_annotation() -> None:
    def missing_param_annotation(value) -> int:
        """Bad tool."""
        return int(value)

    with pytest.raises(ValueError, match="must be annotated"):
        tool(name="missing_param_annotation_tool_test")(missing_param_annotation)


def test_function_tool_rejects_missing_return_annotation() -> None:
    def missing_return_annotation(value: int):
        """Bad tool."""
        return value

    with pytest.raises(ValueError, match="must declare a return type"):
        tool(name="missing_return_annotation_tool_test")(missing_return_annotation)


def test_function_tool_rejects_varargs_signature() -> None:
    def bad_varargs(*values: int) -> int:
        """Bad tool."""
        return sum(values)

    with pytest.raises(ValueError, match="unsupported parameter kind"):
        tool(name="bad_varargs_tool_test")(bad_varargs)


def test_function_tool_conflict_with_openhands_name_raises_immediately() -> None:
    def conflict(command: str) -> str:
        """Conflicts with the built-in terminal tool."""
        return command

    with pytest.raises(ValueError, match="already registered in OpenHands"):
        tool(name="terminal")(conflict)


def test_function_tool_conflict_with_existing_pyflow_name_raises_immediately() -> None:
    @tool(name="duplicate_pyflow_tool_test")
    def first(value: int) -> int:
        """First definition."""
        return value

    assert isinstance(first, FunctionTool)

    def second(value: str) -> str:
        """Second definition."""
        return value

    with pytest.raises(ValueError, match="different definition"):
        tool(name="duplicate_pyflow_tool_test")(second)


def test_request_attachment_operator_accepts_tools() -> None:
    @tool(name="attachment_lookup_tool_test")
    def attachment_lookup(text: str) -> str:
        """Attachment lookup tool."""
        return text

    step = "Fix this." @ tool("attachment_lookup_tool_test")

    assert step.attachments[0] is attachment_lookup
    assert step.render().endswith("Use tool: attachment_lookup_tool_test.")


def test_agent_default_tools_resolve_to_terminal_read_file_and_apply_patch() -> None:
    agent = Agent(model=_empty_test_model())
    openhands_agent = agent._build_openhands_agent()

    assert [tool_spec.name for tool_spec in openhands_agent.tools] == [
        "terminal",
        "read_file",
        "apply_patch",
    ]


def test_builtin_openhands_tools_compile_to_expected_specs() -> None:
    specs = compile_openhands_tools((terminal_tool, read_file_tool, apply_patch_tool))
    assert [tool_spec.name for tool_spec in specs] == [
        "terminal",
        "read_file",
        "apply_patch",
    ]


def test_agent_uses_only_agent_tools_for_runtime_registration() -> None:
    @tool(name="merge_request_tool_test")
    def summarize_issue(issue: str) -> str:
        """Summarize an issue string."""
        return issue.upper()

    agent = Agent(
        model=_empty_test_model(),
        tools=(terminal_tool, summarize_issue),
    )
    request = Request(
        steps=(
            ("Fix this." @ tool("merge_request_tool_test") @ read_file_tool @ apply_patch_tool),
        )
    )
    rendered_request = request.render()
    assert "Use tool: merge_request_tool_test." in rendered_request
    assert "Use tool: read_file." in rendered_request
    assert "Use tool: apply_patch." in rendered_request
    openhands_agent = agent._build_openhands_agent()

    assert [tool_spec.name for tool_spec in openhands_agent.tools] == [
        "terminal",
        "merge_request_tool_test",
    ]


def test_compile_raises_for_same_name_with_incompatible_tool_identity() -> None:
    @tool(name="incompatible_identity_tool_test")
    def local_tool(value: str) -> str:
        """Local pyflow tool."""
        return value

    wrapped_tool = FunctionTool.from_openhands(
        name="incompatible_identity_tool_test",
        module_name="nonexistent.module.path",
    )

    with pytest.raises(ValueError, match="incompatible definitions"):
        compile_openhands_tools((local_tool, wrapped_tool))


def test_unknown_named_tool_fails_early() -> None:
    with pytest.raises(ValueError, match="Unknown pyflow tool"):
        tool("definitely_unknown_tool_test")


def test_function_tool_executes_via_openhands_tool_loop() -> None:
    @tool(name="execute_add_numbers_tool_test")
    def add_numbers(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    model = TestModel(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="")],
                tool_calls=[
                    MessageToolCall(
                        id="call_add",
                        name="execute_add_numbers_tool_test",
                        arguments='{"a": 1, "b": 2}',
                        origin="completion",
                    )
                ],
            ),
            _finish_message("call_finish"),
        )
    )
    agent = Agent(model=model, tools=(add_numbers,))
    session = agent.run(_prompt_request("Add the numbers."))

    assert isinstance(session, Session)
    events = cast(Any, session.conversation).state.events

    action_event = next(
        event
        for event in events
        if isinstance(event, ActionEvent)
        and event.tool_name == "execute_add_numbers_tool_test"
    )
    observation_event = next(
        event
        for event in events
        if isinstance(event, ObservationEvent)
        and event.tool_name == "execute_add_numbers_tool_test"
    )

    assert action_event.action is not None
    assert observation_event.observation.model_dump()["result"] == 3
    assert observation_event.observation.text == "3"


def test_session_continuation_does_not_register_request_attached_tools() -> None:
    @tool(name="session_attachment_is_prompt_only_tool_test")
    def passthrough(value: str) -> str:
        """Return the provided text unchanged."""
        return value

    model = TestModel(
        scripted_responses=(
            _finish_message("first_run"),
            _finish_message("second_run"),
        )
    )

    # Built-in tools are irrelevant here; skip them to keep continuation tests fast.
    session = "Start a session." >> Agent(model=model, tools=())
    _ = ("This attachment is prompt-only." @ passthrough) >> session

    tool_names = [tool_spec.name for tool_spec in cast(Any, session.conversation).agent.tools]

    assert "session_attachment_is_prompt_only_tool_test" not in tool_names


def _empty_test_model() -> TestModel:
    return TestModel(scripted_responses=())


def _prompt_request(text: str) -> Request:
    return Request(steps=(PromptStep(text=text),))


def _finish_message(call_id: str, message: str = "Done") -> Message:
    return Message(
        role="assistant",
        content=[TextContent(text="")],
        tool_calls=[
            MessageToolCall(
                id=call_id,
                name="finish",
                arguments='{"message": "' + message + '"}',
                origin="completion",
            )
        ],
    )


class _EchoObservation(Observation):
    echoed: str
