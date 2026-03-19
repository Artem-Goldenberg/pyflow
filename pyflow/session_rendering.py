from __future__ import annotations

import json

from dataclasses import dataclass, field
from html import escape
from typing import Literal, Sequence

from openhands.sdk.event import (
    ACPToolCallEvent,
    ActionEvent,
    AgentErrorEvent,
    HookExecutionEvent,
    MessageEvent,
    ObservationEvent,
    PauseEvent,
    UserRejectObservation,
)
from openhands.sdk.event.base import Event
from openhands.sdk.llm import TextContent, content_to_str
from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderResult, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from pyflow.utils import indent_multiline


_TurnRole = Literal["user", "agent", "system"]
_ToolStatus = Literal["pending", "completed", "error", "rejected"]


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

    def render_html(self) -> str:
        if not self.turns:
            return (
                f"{_session_html_style()}"
                '<section class="pyflow-session">'
                '<div class="pyflow-session__empty">Session has no recorded events.</div>'
                "</section>"
            )

        tool_count = sum(len(turn.tool_calls) for turn in self.turns)
        header_summary = (
            f"{len(self.turns)} turn{'s' if len(self.turns) != 1 else ''}"
            f" · {tool_count} tool call{'s' if tool_count != 1 else ''}"
        )

        parts = [_session_html_style(), '<section class="pyflow-session">']
        parts.append('<div class="pyflow-session__header">')
        parts.append('<div class="pyflow-session__title-group">')
        parts.append('<div class="pyflow-session__eyebrow">pyflow session</div>')
        parts.append('<div class="pyflow-session__title">Conversation Transcript</div>')
        parts.append(
            f'<div class="pyflow-session__summary">{escape(header_summary)}</div>'
        )
        parts.append("</div>")
        if self.execution_status:
            parts.append(_render_html_status_chip(self.execution_status))
        parts.append("</div>")

        status_banner = _render_html_status_banner(self)
        if status_banner:
            parts.append(status_banner)

        parts.extend(_render_html_turn(turn) for turn in self.turns)
        parts.append("</section>")
        return "".join(parts)

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
) -> SessionTranscript:
    turns: list[SessionTurn] = []
    pending_tool_calls: dict[str, SessionToolCall] = {}
    last_agent_turn: SessionTurn | None = None

    for event in events:
        if isinstance(event, MessageEvent):
            message_text = _message_event_text(event)
            if event.llm_message.role == "user":
                turn = SessionTurn(role="user")
                if message_text:
                    turn.messages.append(message_text)
                turns.append(turn)
                last_agent_turn = None
                continue
            if event.llm_message.role == "assistant":
                turn = SessionTurn(role="agent", response_id=event.llm_response_id)
                if message_text:
                    turn.messages.append(message_text)
                turns.append(turn)
                last_agent_turn = turn
                continue
            if message_text:
                turn = SessionTurn(role="system")
                turn.messages.append(message_text)
                turns.append(turn)
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

    for tool_call in turn.tool_calls:
        if parts:
            parts.append(Text())
        parts.append(_render_tool_call(tool_call))

    if not parts:
        parts.append(Text("[empty]", style="dim"))

    return Group(*parts)


def _render_tool_call(tool_call: SessionToolCall) -> Panel:
    content: list[RenderableType] = [
        Text(f"tool call: {tool_call.tool_name}", style="bold"),
    ]

    if tool_call.arguments:
        content.append(Text("arguments", style="dim"))
        content.append(_render_code_block(tool_call.arguments))

    if tool_call.result:
        content.append(Text(_tool_status_label(tool_call.status).lower(), style="dim"))
        content.append(_render_code_block(tool_call.result))

    return Panel(
        Group(*content),
        border_style=_tool_status_border_style(tool_call.status),
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _render_code_block(content: str) -> RenderableType:
    if _looks_like_json(content):
        return Syntax(_format_jsonish(content), "json", word_wrap=True)
    return Text(content)


def _render_html_turn(turn: SessionTurn) -> str:
    role_class = f"pyflow-session__row--{turn.role}"
    bubble_class = f"pyflow-session__bubble--{turn.role}"
    parts = [f'<div class="pyflow-session__row {role_class}">']
    parts.append(f'<article class="pyflow-session__bubble {bubble_class}">')
    parts.append(
        '<div class="pyflow-session__bubble-head">'
        f'<span class="pyflow-session__role">{escape(_role_label(turn.role))}</span>'
        "</div>"
    )

    for message in turn.messages:
        parts.append(
            '<div class="pyflow-session__message">'
            f"{escape(message)}"
            "</div>"
        )

    for tool_call in turn.tool_calls:
        parts.append(_render_html_tool_call(tool_call))

    if not turn.messages and not turn.tool_calls:
        parts.append('<div class="pyflow-session__empty-turn">[empty]</div>')

    parts.append("</article>")
    parts.append("</div>")
    return "".join(parts)


def _render_html_tool_call(tool_call: SessionToolCall) -> str:
    parts = ['<section class="pyflow-tool-call">']
    parts.append('<div class="pyflow-tool-call__header">')
    parts.append(
        '<div class="pyflow-tool-call__title-group">'
        '<div class="pyflow-tool-call__eyebrow">tool call</div>'
        f'<div class="pyflow-tool-call__title">{escape(tool_call.tool_name)}</div>'
        "</div>"
    )
    parts.append(_render_html_tool_status(tool_call.status))
    parts.append("</div>")

    if tool_call.arguments:
        parts.append('<div class="pyflow-tool-call__section-label">Arguments</div>')
        parts.append(_render_html_code_block(_format_jsonish(tool_call.arguments)))

    if tool_call.result:
        parts.append(
            '<div class="pyflow-tool-call__section-label">'
            f"{escape(_tool_status_label(tool_call.status))}"
            "</div>"
        )
        parts.append(_render_html_code_block(tool_call.result))
    elif tool_call.status == "pending":
        parts.append(
            '<div class="pyflow-tool-call__hint">'
            "Awaiting approval or execution."
            "</div>"
        )

    parts.append("</section>")
    return "".join(parts)


def _render_html_code_block(content: str) -> str:
    return (
        '<pre class="pyflow-tool-call__code"><code>'
        f"{escape(content)}"
        "</code></pre>"
    )


def _render_html_tool_status(status: _ToolStatus) -> str:
    return (
        '<span class="pyflow-tool-call__status '
        f'pyflow-tool-call__status--{escape(status)}">'
        f"{escape(_tool_status_label(status))}"
        "</span>"
    )


def _render_html_status_chip(status: str) -> str:
    normalized = _normalize_status_value(status)
    return (
        '<div class="pyflow-session__status '
        f'pyflow-session__status--{escape(normalized)}">'
        f"{escape(_format_status_label(normalized))}"
        "</div>"
    )


def _render_html_status_banner(transcript: SessionTranscript) -> str:
    pending_tool_names = [
        tool_call.tool_name
        for turn in transcript.turns
        for tool_call in turn.tool_calls
        if tool_call.status == "pending"
    ]
    status = _normalize_status_value(transcript.execution_status)

    if status == "waiting_for_confirmation":
        pending = ", ".join(dict.fromkeys(pending_tool_names)) or "pending tool action"
        return (
            '<aside class="pyflow-session__banner pyflow-session__banner--pending">'
            '<div class="pyflow-session__banner-title">Approval required</div>'
            f"<div>This session is waiting for confirmation for {escape(pending)}.</div>"
            "<div>Continue with <code>session.approve_pending_actions()</code> "
            "or reject with <code>session.reject_pending_actions()</code>.</div>"
            "</aside>"
        )

    if status == "paused":
        return (
            '<aside class="pyflow-session__banner pyflow-session__banner--paused">'
            '<div class="pyflow-session__banner-title">Paused</div>'
            "<div>The conversation is paused and can be resumed with "
            "<code>session.approve_pending_actions()</code> or "
            "<code>session.conversation.run()</code>.</div>"
            "</aside>"
        )

    if status in {"error", "stuck"}:
        return (
            '<aside class="pyflow-session__banner pyflow-session__banner--error">'
            f'<div class="pyflow-session__banner-title">{escape(_format_status_label(status))}</div>'
            "<div>The latest run did not complete cleanly. Review the tool output "
            "and system events below.</div>"
            "</aside>"
        )

    return ""


def _session_html_style() -> str:
    return """
<style>
.pyflow-session {
  --pyflow-ink: #172033;
  --pyflow-muted: #586377;
  --pyflow-line: rgba(27, 39, 61, 0.12);
  --pyflow-surface: rgba(255, 255, 255, 0.88);
  --pyflow-surface-strong: rgba(255, 255, 255, 0.96);
  --pyflow-user: linear-gradient(135deg, #d8f0ff 0%, #eef7ff 100%);
  --pyflow-agent: linear-gradient(145deg, #fffdf8 0%, #ffffff 100%);
  --pyflow-system: linear-gradient(145deg, #fff5df 0%, #fffdf8 100%);
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--pyflow-ink);
  background:
    radial-gradient(circle at top left, rgba(73, 173, 255, 0.16), transparent 32%),
    radial-gradient(circle at top right, rgba(255, 173, 96, 0.18), transparent 28%),
    linear-gradient(180deg, #f5f8ff 0%, #fbfcff 100%);
  border: 1px solid rgba(88, 99, 119, 0.16);
  border-radius: 24px;
  box-shadow: 0 18px 40px rgba(19, 34, 58, 0.08);
  padding: 20px;
}
.pyflow-session__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.pyflow-session__eyebrow,
.pyflow-tool-call__eyebrow {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--pyflow-muted);
  margin-bottom: 4px;
}
.pyflow-session__title {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
}
.pyflow-session__summary {
  color: var(--pyflow-muted);
  font-size: 13px;
  margin-top: 6px;
}
.pyflow-session__status {
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid transparent;
  background: rgba(34, 197, 94, 0.12);
  color: #166534;
}
.pyflow-session__status--waiting_for_confirmation {
  background: rgba(245, 158, 11, 0.14);
  color: #9a6700;
}
.pyflow-session__status--paused {
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}
.pyflow-session__status--error,
.pyflow-session__status--stuck {
  background: rgba(239, 68, 68, 0.12);
  color: #b42318;
}
.pyflow-session__banner {
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 18px;
  border: 1px solid var(--pyflow-line);
  background: rgba(255, 255, 255, 0.7);
}
.pyflow-session__banner-title {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 6px;
}
.pyflow-session__banner--pending {
  background: rgba(255, 244, 222, 0.85);
  border-color: rgba(217, 119, 6, 0.18);
}
.pyflow-session__banner--paused {
  background: rgba(224, 240, 255, 0.82);
  border-color: rgba(37, 99, 235, 0.16);
}
.pyflow-session__banner--error {
  background: rgba(255, 233, 233, 0.82);
  border-color: rgba(220, 38, 38, 0.16);
}
.pyflow-session__row {
  display: flex;
  margin-top: 14px;
}
.pyflow-session__row--user {
  justify-content: flex-end;
}
.pyflow-session__row--agent,
.pyflow-session__row--system {
  justify-content: flex-start;
}
.pyflow-session__bubble {
  width: min(100%, 860px);
  border-radius: 20px;
  padding: 14px 16px;
  border: 1px solid var(--pyflow-line);
  box-shadow: 0 10px 24px rgba(19, 34, 58, 0.05);
  background: var(--pyflow-surface);
}
.pyflow-session__row--user .pyflow-session__bubble {
  max-width: 78%;
}
.pyflow-session__row--agent .pyflow-session__bubble,
.pyflow-session__row--system .pyflow-session__bubble {
  max-width: 88%;
}
.pyflow-session__bubble--user {
  background: var(--pyflow-user);
}
.pyflow-session__bubble--agent {
  background: var(--pyflow-agent);
}
.pyflow-session__bubble--system {
  background: var(--pyflow-system);
}
.pyflow-session__bubble-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.pyflow-session__role {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--pyflow-muted);
  font-weight: 700;
}
.pyflow-session__message {
  white-space: pre-wrap;
  line-height: 1.55;
  margin-top: 10px;
}
.pyflow-session__message:first-of-type {
  margin-top: 0;
}
.pyflow-tool-call {
  margin-top: 14px;
  border-radius: 16px;
  padding: 14px;
  border: 1px solid rgba(63, 80, 113, 0.12);
  background: var(--pyflow-surface-strong);
}
.pyflow-tool-call__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.pyflow-tool-call__title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.25;
}
.pyflow-tool-call__status {
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 700;
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}
.pyflow-tool-call__status--completed {
  background: rgba(34, 197, 94, 0.14);
  color: #166534;
}
.pyflow-tool-call__status--error {
  background: rgba(239, 68, 68, 0.14);
  color: #b42318;
}
.pyflow-tool-call__status--rejected {
  background: rgba(217, 45, 32, 0.16);
  color: #912018;
}
.pyflow-tool-call__section-label {
  margin-top: 12px;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--pyflow-muted);
}
.pyflow-tool-call__hint {
  margin-top: 12px;
  color: var(--pyflow-muted);
  font-size: 13px;
}
.pyflow-tool-call__code {
  margin: 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: #13213a;
  color: #f8fbff;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, "SFMono-Regular", SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
}
.pyflow-session__empty,
.pyflow-session__empty-turn {
  color: var(--pyflow-muted);
}
.pyflow-session code {
  font-family: ui-monospace, "SFMono-Regular", SFMono-Regular, Menlo, monospace;
  background: rgba(19, 33, 58, 0.08);
  border-radius: 6px;
  padding: 0 4px;
}
</style>
"""


def _message_event_text(event: MessageEvent) -> str:
    text_parts = content_to_str(event.to_llm_message().content)
    return "".join(text_parts).strip()


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


def _normalize_status_value(status: str | None) -> str:
    if not status:
        return "idle"
    return status.strip().lower()


def _format_status_label(status: str) -> str:
    return status.replace("_", " ").title()
