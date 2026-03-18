from __future__ import annotations

import importlib
import logging

from pathlib import Path
from typing import Annotated, Any, cast

import pytest

from openhands.sdk import Observation
from openhands.sdk.event import ActionEvent, ObservationEvent
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.tool import ToolAnnotations, resolve_tool

from pyflow import (
    Agent,
    FunctionTool,
    PromptStep,
    Request,
    Session,
    TestModel,
    ToolSet,
    ToolContext,
    apply_patch_tool,
    read_file_tool,
    terminal_tool,
    tool,
    tools,
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
    assert tools("render_alpha_tool_test", "render_beta_tool_test").render() == (
        "Use tools: render_alpha_tool_test, render_beta_tool_test."
    )


def test_builtin_openhands_tools_are_wrapped_as_function_tools() -> None:
    assert isinstance(terminal_tool, FunctionTool)
    assert isinstance(read_file_tool, FunctionTool)
    assert isinstance(apply_patch_tool, FunctionTool)


def test_tools_resolves_registered_local_tool() -> None:
    @tool(name="count_letters_tool_test")
    def count_letters(text: str) -> int:
        """Count the number of characters in the input."""
        return len(text)

    looked_up = tools("count_letters_tool_test")

    assert looked_up is count_letters
    assert isinstance(count_letters, FunctionTool)
    assert count_letters.name == "count_letters_tool_test"


def test_tools_resolves_openhands_wrapped_tool() -> None:
    looked_up = tools("read_file")

    assert isinstance(looked_up, FunctionTool)
    assert looked_up.name == "read_file"
    assert looked_up is read_file_tool


def test_tools_groups_multiple_tools() -> None:
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

    single = tools("toolset_one_tool_test")
    combined = tools(
        "toolset_one_tool_test",
        tools("toolset_two_tool_test", "toolset_three_tool_test"),
    )

    assert single is first
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


def test_tool_decorator_maps_annotation_kwargs_to_registered_definition() -> None:
    @tool(
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=False,
    )
    def decorator_annotation_kwargs_tool_test(text: str) -> str:
        """Expose tool annotations via decorator kwargs."""
        return text

    expected_annotations = ToolAnnotations(
        title="decorator_annotation_kwargs_tool_test",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    registered_definition = resolve_tool(
        decorator_annotation_kwargs_tool_test.to_openhands_spec(),
        cast(Any, None),
    )[0]

    assert decorator_annotation_kwargs_tool_test.annotations == expected_annotations
    assert registered_definition.annotations == expected_annotations


def test_function_tool_from_function_maps_annotation_kwargs() -> None:
    def from_function_annotation_kwargs(value: str) -> str:
        """Expose tool annotations via FunctionTool.from_function."""
        return value

    configured_tool = FunctionTool.from_function(
        from_function_annotation_kwargs,
        name="from_function_annotation_kwargs_tool_test",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=False,
    )
    expected_annotations = ToolAnnotations(
        title="from_function_annotation_kwargs_tool_test",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    registered_definition = resolve_tool(
        configured_tool.to_openhands_spec(),
        cast(Any, None),
    )[0]

    assert configured_tool.annotations == expected_annotations
    assert registered_definition.annotations == expected_annotations


def test_function_tool_preserves_annotated_parameter_metadata() -> None:
    @tool(name="annotated_parameter_tool_test")
    def annotate(value: Annotated[int, "positive"]) -> str:
        """Expose annotated metadata in the generated action schema."""
        return str(value)

    field_info = annotate.action_type.model_fields["value"]

    assert field_info.annotation is int
    assert field_info.metadata == ["positive"]


def test_function_tool_uses_observation_return_annotation_directly() -> None:
    @tool(name="echo_observation_tool_test")
    def echo_text(text: str) -> _EchoObservation:
        """Return a typed observation."""
        return _EchoObservation(
            echoed=text,
            content=[TextContent(text=text)],
        )

    assert echo_text.observation_type is _EchoObservation


def test_function_tool_injects_tool_context_and_excludes_it_from_schema() -> None:
    observed_contexts: list[ToolContext] = []

    @tool(name="tool_context_injection_tool_test")
    def inspect_context(ctx: ToolContext, value: str) -> str:
        """Capture runtime tool context."""
        observed_contexts.append(ctx)
        return value.upper()

    model = TestModel(
        scripted_responses=(
            Message(
                role="assistant",
                content=[TextContent(text="")],
                tool_calls=[
                    MessageToolCall(
                        id="call_context",
                        name="tool_context_injection_tool_test",
                        arguments='{"value": "hello"}',
                        origin="completion",
                    )
                ],
            ),
            _finish_message("call_finish"),
        )
    )
    session = Agent(model=model, tools=(inspect_context,)).run(
        _prompt_request("Use the tool.")
    )
    events = cast(Any, session.conversation).state.events
    observation_event = next(
        event
        for event in events
        if isinstance(event, ObservationEvent)
        and event.tool_name == "tool_context_injection_tool_test"
    )

    assert list(inspect_context.action_type.model_fields) == ["value"]
    assert len(observed_contexts) == 1
    assert observed_contexts[0].conversation is session.conversation
    assert observation_event.observation.model_dump()["result"] == "HELLO"


def test_function_tool_requires_tool_context_to_be_first_parameter() -> None:
    def invalid_tool_context_parameter(value: str, ctx: ToolContext) -> str:
        """Invalid tool context placement."""
        return value

    with pytest.raises(ValueError, match="first parameter"):
        tool(name="invalid_tool_context_position_tool_test")(
            invalid_tool_context_parameter
        )


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


def test_function_tool_redefinition_warns_and_replaces_existing_definition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @tool(name="duplicate_pyflow_tool_test")
    def first(value: int) -> int:
        """First definition."""
        return value

    assert isinstance(first, FunctionTool)

    caplog.set_level(logging.WARNING, logger="pyflow.tooling")

    @tool(name="duplicate_pyflow_tool_test")
    def second(value: str) -> str:
        """Second definition."""
        return value

    looked_up = tools("duplicate_pyflow_tool_test")

    assert looked_up is second
    assert second.action_type.model_fields["value"].annotation is str
    assert second("value") == "value"
    assert "Replacing tool 'duplicate_pyflow_tool_test'" in caplog.text


def test_function_tool_can_replace_existing_openhands_tool_name(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING, logger="pyflow.tooling")

    tool_name = "wrapped_conflict_tool_test"
    module_name = _write_openhands_tool_module(
        tmp_path,
        module_name="wrapped_conflict_tool_module",
        tool_name=tool_name,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    wrapped_tool = FunctionTool.from_openhands(
        name=tool_name,
        module_name=module_name,
    )

    @tool(name=tool_name)
    def conflict(value: str) -> str:
        """Replace an imported OpenHands-backed tool."""
        return f"custom:{value}"

    assert wrapped_tool.name == tool_name
    assert tools(tool_name) is conflict
    assert "Replacing tool 'wrapped_conflict_tool_test'" in caplog.text


def test_request_attachment_operator_accepts_tools() -> None:
    @tool(name="attachment_lookup_tool_test")
    def attachment_lookup(text: str) -> str:
        """Attachment lookup tool."""
        return text

    step = "Fix this." @ tools("attachment_lookup_tool_test")

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
            ("Fix this." @ tools("merge_request_tool_test") @ read_file_tool @ apply_patch_tool),
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


def test_compile_keeps_last_tool_for_duplicate_names() -> None:
    @tool(name="duplicate_compile_tool_test")
    def first(value: int) -> int:
        """First definition."""
        return value

    @tool(name="duplicate_compile_tool_test")
    def second(value: str) -> str:
        """Second definition."""
        return value

    specs = compile_openhands_tools((first, second))

    assert [tool_spec.name for tool_spec in specs] == ["duplicate_compile_tool_test"]


def test_unknown_named_tool_fails_early() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        tools("definitely_unknown_tool_test")


def test_tools_requires_at_least_one_value() -> None:
    with pytest.raises(TypeError, match="requires at least one tool"):
        tools()


def test_tools_does_not_accept_definition_kwargs() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'read_only'"):
        cast(Any, tools)("read_file", read_only=True)


def test_tool_lookup_form_is_invalid() -> None:
    with pytest.raises(TypeError, match="Use @tool or @tool\\(\\.\\.\\.\\)"):
        cast(Any, tool)("read_file")


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
                arguments=f'{{"message": "{message}"}}',
                origin="completion",
            )
        ],
    )


class _EchoObservation(Observation):
    echoed: str


def _write_openhands_tool_module(
    tmp_path: Path,
    *,
    module_name: str,
    tool_name: str,
) -> str:
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        "\n".join(
            (
                "from pydantic import create_model",
                "from openhands.sdk.llm import TextContent",
                "from openhands.sdk.tool import (",
                "    Action,",
                "    Observation,",
                "    ToolAnnotations,",
                "    ToolDefinition,",
                "    ToolExecutor,",
                "    register_tool,",
                ")",
                "",
                f"TOOL_NAME = {tool_name!r}",
                "ImportedWrappedConflictAction = create_model(",
                "    'ImportedWrappedConflictAction',",
                "    __base__=Action,",
                "    __module__=__name__,",
                "    value=(str, ...),",
                ")",
                "ImportedWrappedConflictObservation = create_model(",
                "    'ImportedWrappedConflictObservation',",
                "    __base__=Observation,",
                "    __module__=__name__,",
                "    result=(str, ...),",
                ")",
                "",
                "class _Executor(ToolExecutor[Action, Observation]):",
                "    def __call__(self, action: Action, conversation=None) -> Observation:",
                "        return ImportedWrappedConflictObservation.model_validate(",
                "            {",
                "                'result': action.value,",
                "                'content': [TextContent(text=action.value)],",
                "            }",
                "        )",
                "",
                "def _unsupported_create(cls, conv_state=None, **params):",
                "    if params:",
                "        raise ValueError('Temporary wrapped tool does not accept params.')",
                "    raise NotImplementedError('Temporary wrapped tool is a fixed instance.')",
                "",
                "WrappedConflictToolDefinition = type(",
                "    'WrappedConflictToolDefinition',",
                "    (ToolDefinition,),",
                "    {",
                "        '__module__': __name__,",
                "        'name': TOOL_NAME,",
                "        'create': classmethod(_unsupported_create),",
                "    },",
                ")",
                "",
                "register_tool(",
                "    TOOL_NAME,",
                "    WrappedConflictToolDefinition(",
                "        description='Temporary wrapped tool.',",
                "        action_type=ImportedWrappedConflictAction,",
                "        observation_type=ImportedWrappedConflictObservation,",
                "        annotations=ToolAnnotations(",
                "            title=TOOL_NAME,",
                "            readOnlyHint=False,",
                "            destructiveHint=False,",
                "            idempotentHint=True,",
                "            openWorldHint=False,",
                "        ),",
                "        executor=_Executor(),",
                "    ),",
                ")",
            )
        )
        + "\n"
    )
    return module_name
