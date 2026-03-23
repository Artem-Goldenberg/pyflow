from __future__ import annotations

import json

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Sequence

from openhands.sdk import Event, TextContent
from openhands.sdk.event import (
    ACPToolCallEvent,
    ActionEvent,
    AgentErrorEvent,
    HookExecutionEvent,
    MessageEvent,
    ObservationEvent,
    PauseEvent,
    SystemPromptEvent,
    UserRejectObservation,
)
from openhands.sdk.llm import content_to_str
from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderResult, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from pyflow.utils import indent_multiline


_TurnRole = Literal["user", "agent", "system"]
_ToolStatus = Literal["pending", "completed", "error", "rejected"]
_SectionKind = Literal["text", "code"]


class _SessionRenderView(StrEnum):
    LIVE = "live"
    FULL = "full"


@dataclass(kw_only=True)
class _SessionSection:
    title: str
    content: str
    kind: _SectionKind = "text"


@dataclass(kw_only=True)
class SessionToolCall:
    tool_name: str
    tool_call_id: str
    arguments: str
    status: _ToolStatus = "pending"
    result: str | None = None


@dataclass(kw_only=True)
class SessionTurn:
    role: _TurnRole
    response_id: str | None = None
    messages: list[str] = field(default_factory=list)
    sections: list[_SessionSection] = field(default_factory=list)
    tool_calls: list[SessionToolCall] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class SessionTranscript:
    turns: Sequence[SessionTurn]
    execution_status: str | None = None

    def render_text(self) -> str:
        if not self.turns:
            return "Session has no recorded events."

        lines: list[str] = []
        for turn in self.turns:
            lines.append(f"{_role_label(turn.role)}:")
            for message in turn.messages:
                lines.extend(indent_multiline("  ", message))
            for section in turn.sections:
                lines.append(f"  {section.title}:")
                lines.extend(
                    indent_multiline(
                        "    ",
                        _render_text_block(section.content, kind=section.kind),
                    )
                )
            for tool_call in turn.tool_calls:
                lines.append(f"  Tool Call: {tool_call.tool_name}")
                if tool_call.arguments:
                    lines.append("    Arguments:")
                    lines.extend(
                        indent_multiline("      ", _format_jsonish(tool_call.arguments))
                    )
                if tool_call.result:
                    lines.append(f"    {_tool_status_label(tool_call.status)}:")
                    lines.extend(indent_multiline("      ", tool_call.result))
            lines.append("")

        return "\n".join(lines).rstrip()

    def display(self, console: Console | None = None) -> None:
        target = console if console is not None else Console()
        target.print(self)

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        if not self.turns:
            yield Panel(
                Text("Session has no recorded events.", style="dim"),
                border_style="dim",
                box=box.ROUNDED,
            )
            return

        bubble_width = max(36, min(options.max_width, options.max_width * 4 // 5))
        for turn in self.turns:
            panel = Panel(
                _render_turn_body(turn),
                title=_role_label(turn.role),
                title_align="left",
                border_style=_role_border_style(turn.role),
                box=box.ROUNDED,
                width=bubble_width,
                padding=(0, 1),
            )
            if turn.role == "user":
                yield Align.right(panel)
            else:
                yield Align.left(panel)
            yield Text()


def build_transcript(
    events: Sequence[Event],
    *,
    execution_status: str | None = None,
    view: _SessionRenderView = _SessionRenderView.LIVE,
) -> SessionTranscript:
    turns: list[SessionTurn] = []
    pending_tool_calls: dict[str, SessionToolCall] = {}
    last_agent_turn: SessionTurn | None = None

    for event in events:
        if isinstance(event, SystemPromptEvent):
            if view is _SessionRenderView.FULL:
                turn = SessionTurn(role="system")
                turn.sections.append(
                    _SessionSection(
                        title="System Prompt",
                        content=event.system_prompt.text.strip(),
                    )
                )
                if event.dynamic_context is not None and event.dynamic_context.text.strip():
                    turn.sections.append(
                        _SessionSection(
                            title="Dynamic Context",
                            content=event.dynamic_context.text.strip(),
                        )
                    )
                tool_inventory = _tool_inventory_text(event.tools)
                if tool_inventory:
                    turn.sections.append(
                        _SessionSection(title="Tools", content=tool_inventory)
                    )
                turns.append(turn)
                last_agent_turn = None
            continue

        if isinstance(event, MessageEvent):
            message_text = _message_event_text(event)
            prompt_extension = _prompt_extension_text(event)
            if event.llm_message.role == "user":
                turn = SessionTurn(role="user")
                if message_text:
                    turn.messages.append(message_text)
                if view is _SessionRenderView.FULL and prompt_extension:
                    turn.sections.append(
                        _SessionSection(
                            title="Prompt Extension",
                            content=prompt_extension,
                        )
                    )
                turns.append(turn)
                last_agent_turn = None
                continue
            if event.llm_message.role == "assistant":
                turn = SessionTurn(role="agent", response_id=event.llm_response_id)
                if message_text:
                    turn.messages.append(message_text)
                if view is _SessionRenderView.FULL and prompt_extension:
                    turn.sections.append(
                        _SessionSection(
                            title="Prompt Extension",
                            content=prompt_extension,
                        )
                    )
                turns.append(turn)
                last_agent_turn = turn
                continue

            turn = SessionTurn(role="system")
            if message_text:
                turn.messages.append(message_text)
            if view is _SessionRenderView.FULL and prompt_extension:
                turn.sections.append(
                    _SessionSection(
                        title="Prompt Extension",
                        content=prompt_extension,
                    )
                )
            turns.append(turn)
            last_agent_turn = None
            continue

        if isinstance(event, ActionEvent):
            turn = _ensure_agent_turn(
                turns,
                last_agent_turn,
                response_id=event.llm_response_id,
            )
            thought_text = _text_content_sequence_to_text(event.thought)
            if thought_text and thought_text not in turn.messages:
                turn.messages.append(thought_text)

            tool_call = SessionToolCall(
                tool_name=event.tool_name,
                tool_call_id=event.tool_call_id,
                arguments=event.tool_call.arguments,
            )
            turn.tool_calls.append(tool_call)
            pending_tool_calls[event.tool_call_id] = tool_call
            last_agent_turn = turn
            continue

        if isinstance(event, ObservationEvent):
            tool_call = _ensure_tool_call(
                turns,
                pending_tool_calls,
                last_agent_turn,
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
            )
            tool_call.status = "completed"
            tool_call.result = _observation_text(event)
            continue

        if isinstance(event, UserRejectObservation):
            tool_call = _ensure_tool_call(
                turns,
                pending_tool_calls,
                last_agent_turn,
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
            )
            tool_call.status = "rejected"
            tool_call.result = event.rejection_reason
            continue

        if isinstance(event, AgentErrorEvent):
            tool_call = _ensure_tool_call(
                turns,
                pending_tool_calls,
                last_agent_turn,
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
            )
            tool_call.status = "error"
            tool_call.result = event.error
            continue

        if isinstance(event, ACPToolCallEvent):
            turn = _ensure_agent_turn(turns, last_agent_turn, response_id=None)
            tool_call = pending_tool_calls.get(event.tool_call_id)
            if tool_call is None:
                tool_call = SessionToolCall(
                    tool_name=event.title,
                    tool_call_id=event.tool_call_id,
                    arguments=_stringify_value(event.raw_input),
                )
                turn.tool_calls.append(tool_call)
                pending_tool_calls[event.tool_call_id] = tool_call
            elif event.raw_input is not None:
                tool_call.arguments = _stringify_value(event.raw_input)

            tool_call.status = _acp_status(event)
            if event.raw_output is not None:
                tool_call.result = _stringify_value(event.raw_output)

            last_agent_turn = turn
            continue

        if isinstance(event, (HookExecutionEvent, PauseEvent)):
            event_text = _event_visual_text(event)
            if not event_text:
                continue
            turn = SessionTurn(role="system")
            turn.messages.append(event_text)
            turns.append(turn)
            last_agent_turn = None

    return SessionTranscript(turns=turns, execution_status=execution_status)


def _ensure_agent_turn(
    turns: list[SessionTurn],
    last_agent_turn: SessionTurn | None,
    *,
    response_id: str | None,
) -> SessionTurn:
    if (
        last_agent_turn is not None
        and last_agent_turn.role == "agent"
        and last_agent_turn.response_id == response_id
    ):
        return last_agent_turn

    turn = SessionTurn(role="agent", response_id=response_id)
    turns.append(turn)
    return turn


def _ensure_tool_call(
    turns: list[SessionTurn],
    pending_tool_calls: dict[str, SessionToolCall],
    last_agent_turn: SessionTurn | None,
    *,
    tool_call_id: str,
    tool_name: str,
) -> SessionToolCall:
    existing = pending_tool_calls.get(tool_call_id)
    if existing is not None:
        return existing

    turn = _ensure_agent_turn(turns, last_agent_turn, response_id=None)
    tool_call = SessionToolCall(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        arguments="",
    )
    turn.tool_calls.append(tool_call)
    pending_tool_calls[tool_call_id] = tool_call
    return tool_call


def _render_turn_body(turn: SessionTurn) -> Group:
    parts: list[RenderableType] = []

    for index, message in enumerate(turn.messages):
        if index:
            parts.append(Text())
        parts.append(Text(message))

    for section in turn.sections:
        if parts:
            parts.append(Text())
        parts.append(_render_section(section))

    for tool_call in turn.tool_calls:
        if parts:
            parts.append(Text())
        parts.append(_render_tool_call(tool_call))

    if not parts:
        parts.append(Text("[empty]", style="dim"))

    return Group(*parts)


def _render_section(section: _SessionSection) -> Group:
    return Group(
        Text(section.title, style="dim"),
        _render_code_block(section.content, kind=section.kind),
    )


def _render_tool_call(tool_call: SessionToolCall) -> Panel:
    content: list[RenderableType] = [
        Text(f"tool call: {tool_call.tool_name}", style="bold"),
    ]

    if tool_call.arguments:
        content.append(Text("arguments", style="dim"))
        content.append(_render_code_block(tool_call.arguments, kind="code"))

    if tool_call.result:
        content.append(Text(_tool_status_label(tool_call.status).lower(), style="dim"))
        content.append(_render_code_block(tool_call.result, kind="code"))

    return Panel(
        Group(*content),
        border_style=_tool_status_border_style(tool_call.status),
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _render_code_block(content: str, *, kind: _SectionKind) -> RenderableType:
    if kind == "code" and _looks_like_json(content):
        return Syntax(_format_jsonish(content), "json", word_wrap=True)
    if kind == "code":
        return Text(content)
    if _looks_like_json(content):
        return Syntax(_format_jsonish(content), "json", word_wrap=True)
    return Text(content)


def _render_text_block(content: str, *, kind: _SectionKind) -> str:
    if kind == "code":
        return _format_jsonish(content)
    return content


def _message_event_text(event: MessageEvent) -> str:
    text_parts = content_to_str(event.to_llm_message().content)
    return "".join(text_parts).strip()


def _prompt_extension_text(event: MessageEvent) -> str:
    return _text_content_sequence_to_text(event.extended_content)


def _tool_inventory_text(tools: Sequence[object]) -> str:
    lines: list[str] = []
    for tool in tools:
        name = str(getattr(tool, "name", type(tool).__name__))
        description = str(getattr(tool, "description", "")).strip()
        summary = description.splitlines()[0].strip() if description else ""
        lines.append(f"- {name}: {summary or 'No description provided.'}")
        arguments_schema = _tool_arguments_schema(tool)
        if arguments_schema is None:
            continue
        lines.append("  Arguments Schema:")
        lines.extend(f"    {line}" for line in arguments_schema.splitlines())
    return "\n".join(lines).strip()


def _observation_text(event: ObservationEvent) -> str:
    return "".join(content_to_str(event.observation.to_llm_content)).strip()


def _text_content_sequence_to_text(content: Sequence[TextContent]) -> str:
    return "\n".join(text.text for text in content if text.text).strip()


def _event_visual_text(event: Event) -> str:
    visualize = getattr(event, "visualize", None)
    if visualize is None:
        return str(event).strip()
    plain = getattr(visualize, "plain", "")
    return str(plain).strip()


def _stringify_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, sort_keys=True)
    except TypeError:
        return str(value)


def _acp_status(event: ACPToolCallEvent) -> _ToolStatus:
    if event.is_error:
        return "error"
    normalized = (event.status or "").strip().lower()
    if normalized in {"success", "succeeded", "completed", "complete", "done", "finished"}:
        return "completed"
    if normalized in {"rejected", "denied", "blocked"}:
        return "rejected"
    if normalized in {"error", "failed", "failure"}:
        return "error"
    return "pending"


def _format_jsonish(content: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content
    return json.dumps(parsed, indent=2, sort_keys=True)


def _tool_arguments_schema(tool: object) -> str | None:
    action_type = getattr(tool, "action_type", None)
    if action_type is None or not hasattr(action_type, "to_mcp_schema"):
        return None
    return json.dumps(action_type.to_mcp_schema(), indent=2, sort_keys=True)


def _looks_like_json(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    return stripped[0] in ("{", "[")


def _role_label(role: _TurnRole) -> str:
    if role == "user":
        return "User"
    if role == "agent":
        return "Agent"
    return "System"


def _role_border_style(role: _TurnRole) -> str:
    if role == "user":
        return "cyan"
    if role == "agent":
        return "green"
    return "magenta"


def _tool_status_label(status: _ToolStatus) -> str:
    if status == "completed":
        return "Result"
    if status == "error":
        return "Error"
    if status == "rejected":
        return "Rejected"
    return "Pending"


def _tool_status_border_style(status: _ToolStatus) -> str:
    if status == "completed":
        return "yellow"
    if status == "error":
        return "red"
    if status == "rejected":
        return "bright_red"
    return "blue"
