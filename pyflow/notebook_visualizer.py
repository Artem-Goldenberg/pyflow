from __future__ import annotations

import json

from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING, Callable, Literal, Protocol, Sequence, cast

import ipywidgets as widgets
from IPython.display import display, display_markdown
from openhands.sdk.conversation.visualizer.base import ConversationVisualizerBase
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
from openhands.sdk.security import risk

if TYPE_CHECKING:
    from openhands.sdk.conversation.base import BaseConversation, ConversationStateProtocol
    from pyflow.session import Session


_TurnRole = Literal["user", "agent", "system"]
_ToolStatus = Literal["pending", "completed", "error", "rejected"]
_SectionKind = Literal["markdown", "code"]


@dataclass(kw_only=True)
class NotebookSection:
    title: str
    content: str
    kind: _SectionKind = "markdown"


@dataclass(kw_only=True)
class NotebookToolCall:
    tool_name: str
    tool_call_id: str
    status: _ToolStatus = "pending"
    summary: str | None = None
    sections: list[NotebookSection] = field(default_factory=list)


@dataclass(kw_only=True)
class NotebookTurn:
    role: _TurnRole
    response_id: str | None = None
    messages: list[str] = field(default_factory=list)
    sections: list[NotebookSection] = field(default_factory=list)
    tool_calls: list[NotebookToolCall] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class NotebookConversationModel:
    turns: Sequence[NotebookTurn]
    execution_status: str | None = None


class NotebookDisplayTarget(Protocol):
    def display_transcript(self, markdown: str) -> None: ...

    def display_controls(self, widget: widgets.Widget) -> None: ...


class _ConversationWithVisualizer(Protocol):
    _visualizer: ConversationVisualizerBase | None


class NotebookConversationVisualizer(ConversationVisualizerBase):
    """Notebook visualizer backed by a Markdown display plus minimal controls."""

    _display_target: NotebookDisplayTarget
    _events: list[Event]
    _seeded_from_state: bool
    _controls: NotebookLiveControls

    def __init__(
        self,
        *,
        display_target: NotebookDisplayTarget | None = None,
        controls: NotebookLiveControls | None = None,
    ) -> None:
        super().__init__()
        self._display_target = (
            display_target if display_target is not None else _IPythonNotebookTarget()
        )
        self._controls = controls if controls is not None else NotebookLiveControls()
        self._events = []
        self._seeded_from_state = False

    @property
    def widget(self) -> widgets.Widget:
        return self._controls.widget

    def bind_session(self, session: Session) -> None:
        self._controls.bind_session(session)

    def on_event(self, event: Event) -> None:
        self._seed_events_from_state()
        self._events.append(event)
        # Notebook frontends like VS Code can surface repeated display updates
        # during a running cell as empty output blocks. Buffer event changes and
        # render once at explicit sync points instead.

    def refresh(self) -> None:
        model = build_notebook_conversation_model(
            self._current_events(),
            execution_status=_execution_status(self._state),
        )
        self._render_model(model)

    def sync_session(self, session: Session) -> None:
        self.bind_session(session)
        model = build_notebook_conversation_model(
            session.events,
            execution_status=session.execution_status,
        )
        self._render_model(model)

    def _render_model(self, model: NotebookConversationModel) -> None:
        self._controls.update_status(model.execution_status)
        self._display_target.display_transcript(render_notebook_markdown(model))
        self._display_target.display_controls(self._controls.widget)

    def _seed_events_from_state(self) -> None:
        if self._seeded_from_state or self._state is None:
            return
        self._events = list(self._state.events)
        self._seeded_from_state = True

    def _current_events(self) -> list[Event]:
        if self._state is None:
            return list(self._events)
        return list(self._state.events)


class NotebookLiveControls:
    """Minimal live controls shown under the notebook transcript."""

    _session: Session | None
    _composer: widgets.Text
    _send_button: widgets.Button
    _approve_button: widgets.Button
    _reject_button: widgets.Button
    _feedback: widgets.Label
    _status: str | None
    _widget: widgets.VBox

    def __init__(self) -> None:
        self._session = None
        self._status = None
        self._composer = widgets.Text(
            placeholder="Continue the conversation…",
            layout=widgets.Layout(width="100%"),
        )
        self._send_button = widgets.Button(
            description="",
            icon="arrow-up",
            tooltip="Send",
            layout=widgets.Layout(width="40px"),
        )
        self._approve_button = widgets.Button(
            description="",
            icon="check",
            tooltip="Approve pending action",
            layout=widgets.Layout(width="40px"),
        )
        self._reject_button = widgets.Button(
            description="",
            icon="times",
            tooltip="Reject pending action",
            layout=widgets.Layout(width="40px"),
        )
        self._feedback = widgets.Label()
        self._widget = widgets.VBox(
            [
                widgets.HBox(
                    [
                        self._composer,
                        self._send_button,
                        self._approve_button,
                        self._reject_button,
                    ],
                    layout=widgets.Layout(width="100%", align_items="center"),
                ),
                self._feedback,
            ]
        )

        self._send_button.on_click(self._on_send)
        self._approve_button.on_click(self._on_approve)
        self._reject_button.on_click(self._on_reject)
        self._update_controls(None)

    @property
    def widget(self) -> widgets.Widget:
        return self._widget

    def bind_session(self, session: Session) -> None:
        self._session = session
        self._clear_feedback()

    def update_status(self, execution_status: str | None) -> None:
        self._status = execution_status
        self._update_controls(execution_status)

    def _on_send(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("Session is not attached to this live view yet.")
            return

        prompt = self._composer.value.strip()
        if not prompt:
            self._set_feedback("Enter a message before sending.")
            return

        session = self._session
        self._run_session_action(lambda: prompt >> session)
        self._composer.value = ""

    def _on_approve(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("Session is not attached to this live view yet.")
            return

        session = self._session
        self._run_session_action(session.approve_pending_actions)

    def _on_reject(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("Session is not attached to this live view yet.")
            return

        reason = "User rejected the action"
        if self._composer.value.strip():
            reason = self._composer.value.strip()

        session = self._session
        self._run_session_action(lambda: session.reject_pending_actions(reason))
        if self._composer.value.strip():
            self._composer.value = ""

    def _run_session_action(self, action: Callable[[], object]) -> None:
        self._set_feedback("Running…")
        self._set_busy(True)
        try:
            action()
            self._clear_feedback()
        except Exception as exc:
            self._set_feedback(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._update_controls(self._status)

    def _set_busy(self, is_busy: bool) -> None:
        self._composer.disabled = is_busy
        self._send_button.disabled = is_busy
        self._approve_button.disabled = is_busy
        self._reject_button.disabled = is_busy

    def _update_controls(self, execution_status: str | None) -> None:
        normalized = _normalize_status_value(execution_status)
        can_send = normalized not in {
            "running",
            "waiting_for_confirmation",
            "paused",
        }
        self._composer.disabled = not can_send
        self._send_button.disabled = not can_send
        self._approve_button.disabled = normalized not in {
            "waiting_for_confirmation",
            "paused",
        }
        self._reject_button.disabled = normalized != "waiting_for_confirmation"

    def _set_feedback(self, message: str) -> None:
        self._feedback.value = message

    def _clear_feedback(self) -> None:
        self._feedback.value = ""


class NotebookSessionWidget:
    """Read-only notebook widget fallback for explicit widget rendering."""

    _output: widgets.Output
    _widget: widgets.VBox
    _last_markdown: str | None

    def __init__(self) -> None:
        self._output = widgets.Output()
        self._widget = widgets.VBox([self._output])
        self._last_markdown = None

    @property
    def widget(self) -> widgets.Widget:
        return self._widget

    def render(self, markdown: str) -> None:
        if markdown == self._last_markdown:
            return
        self._last_markdown = markdown
        self._output.clear_output(wait=True)
        with self._output:
            display_markdown(markdown, raw=True)

    def mimebundle(self, *, text_plain: str, text_markdown: str) -> dict[str, object]:
        return {
            "text/plain": text_plain,
            "text/markdown": text_markdown,
        }


class _IPythonNotebookTarget:
    _transcript_widget: NotebookSessionWidget | None
    _controls_displayed: bool

    def __init__(self) -> None:
        self._transcript_widget = None
        self._controls_displayed = False

    def display_transcript(self, markdown: str) -> None:
        if self._transcript_widget is None:
            self._transcript_widget = NotebookSessionWidget()
            self._transcript_widget.render(markdown)
            display(self._transcript_widget.widget)
            return
        self._transcript_widget.render(markdown)

    def display_controls(self, widget: widgets.Widget) -> None:
        if self._controls_displayed:
            return
        display(widget)
        self._controls_displayed = True


def build_notebook_conversation_model(
    events: Sequence[Event],
    *,
    execution_status: str | None = None,
) -> NotebookConversationModel:
    turns: list[NotebookTurn] = []
    pending_tool_calls: dict[str, NotebookToolCall] = {}
    last_agent_turn: NotebookTurn | None = None

    for event in events:
        if isinstance(event, MessageEvent):
            message_text = _message_event_text(event)
            if event.llm_message.role == "user":
                turn = NotebookTurn(role="user")
                if message_text:
                    turn.messages.append(message_text)
                turns.append(turn)
                last_agent_turn = None
                continue

            if event.llm_message.role == "assistant":
                turn = NotebookTurn(role="agent", response_id=event.llm_response_id)
                if message_text:
                    turn.messages.append(message_text)
                reasoning = _message_reasoning_text(event)
                if reasoning:
                    turn.sections.append(
                        NotebookSection(title="Reasoning", content=reasoning)
                    )
                turns.append(turn)
                last_agent_turn = turn
                continue

            turn = NotebookTurn(role="system")
            if message_text:
                turn.messages.append(message_text)
            turns.append(turn)
            continue

        if isinstance(event, ActionEvent):
            turn = _ensure_agent_turn(
                turns,
                last_agent_turn,
                response_id=event.llm_response_id,
            )
            tool_call = NotebookToolCall(
                tool_name=event.tool_name,
                tool_call_id=event.tool_call_id,
                summary=event.summary,
            )
            if event.tool_call.arguments:
                tool_call.sections.append(
                    NotebookSection(
                        title="Arguments",
                        content=_format_jsonish(event.tool_call.arguments),
                        kind="code",
                    )
                )
            reasoning = _action_reasoning_text(event)
            if reasoning:
                tool_call.sections.append(
                    NotebookSection(title="Reasoning", content=reasoning)
                )
            security_note = _security_risk_text(event)
            if security_note:
                tool_call.sections.append(
                    NotebookSection(title="Security", content=security_note)
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
            _upsert_section(
                tool_call.sections,
                NotebookSection(
                    title="Result",
                    content=_observation_text(event),
                    kind="code",
                ),
            )
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
            _upsert_section(
                tool_call.sections,
                NotebookSection(
                    title="Rejected",
                    content=event.rejection_reason,
                    kind="code",
                ),
            )
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
            _upsert_section(
                tool_call.sections,
                NotebookSection(title="Error", content=event.error, kind="code"),
            )
            continue

        if isinstance(event, ACPToolCallEvent):
            turn = _ensure_agent_turn(turns, last_agent_turn, response_id=None)
            tool_call = pending_tool_calls.get(event.tool_call_id)
            if tool_call is None:
                tool_call = NotebookToolCall(
                    tool_name=event.title,
                    tool_call_id=event.tool_call_id,
                )
                turn.tool_calls.append(tool_call)
                pending_tool_calls[event.tool_call_id] = tool_call
            tool_call.status = _acp_status(event)
            tool_call.summary = _acp_summary(event)
            if event.raw_input is not None:
                _upsert_section(
                    tool_call.sections,
                    NotebookSection(
                        title="Arguments",
                        content=_stringify_value(event.raw_input),
                        kind="code",
                    ),
                )
            if event.raw_output is not None:
                _upsert_section(
                    tool_call.sections,
                    NotebookSection(
                        title="Result",
                        content=_stringify_value(event.raw_output),
                        kind="code",
                    ),
                )
            last_agent_turn = turn
            continue

        if isinstance(event, (HookExecutionEvent, PauseEvent)):
            event_text = _event_visual_text(event)
            if not event_text:
                continue
            turns.append(NotebookTurn(role="system", messages=[event_text]))

    return NotebookConversationModel(turns=turns, execution_status=execution_status)


def render_notebook_markdown(model: NotebookConversationModel) -> str:
    if not model.turns:
        return "## pyflow session\n\n_Session has no recorded events._"

    tool_count = sum(len(turn.tool_calls) for turn in model.turns)
    summary = (
        f"{len(model.turns)} turn{'s' if len(model.turns) != 1 else ''}"
        f" · {tool_count} tool call{'s' if tool_count != 1 else ''}"
    )
    status = _format_status_label(_normalize_status_value(model.execution_status))

    parts = [
        "## pyflow session",
        "",
        f"Status: **{status}**",
        "",
        summary,
    ]

    banner = _banner_markdown(model)
    if banner:
        parts.extend(["", banner])

    for turn in model.turns:
        parts.extend(["", f"### {_role_label(turn.role)}"])

        messages = turn.messages or ["_No direct message content._"]
        for message in messages:
            parts.extend(["", message])

        for section in turn.sections:
            parts.extend(["", _details_block(section.title, _section_body(section))])

        for tool_call in turn.tool_calls:
            parts.extend(["", _tool_call_block(tool_call)])

    return "\n".join(parts).strip()


def notebook_markdown_for_session(session: Session) -> str:
    return render_notebook_markdown(
        build_notebook_conversation_model(
            session.events,
            execution_status=session.execution_status,
        )
    )


def notebook_widget_for_session(session: Session) -> widgets.Widget:
    widget = _read_only_widget_for_session(session)
    widget.render(notebook_markdown_for_session(session))
    return widget.widget


def notebook_mimebundle_for_session(
    session: Session,
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> dict[str, object]:
    del include, exclude
    widget = _read_only_widget_for_session(session)
    markdown = notebook_markdown_for_session(session)
    widget.render(markdown)
    return widget.mimebundle(
        text_plain=session.render(),
        text_markdown=markdown,
    )


def sync_notebook_session(session: Session) -> None:
    visualizer = _conversation_visualizer(session.conversation)
    if isinstance(visualizer, NotebookConversationVisualizer):
        visualizer.sync_session(session)

    if session._notebook_widget is not None:
        session._notebook_widget.render(notebook_markdown_for_session(session))


def _read_only_widget_for_session(session: Session) -> NotebookSessionWidget:
    if session._notebook_widget is None:
        session._notebook_widget = NotebookSessionWidget()
    return session._notebook_widget


def _conversation_visualizer(
    conversation: BaseConversation,
) -> ConversationVisualizerBase | None:
    return cast(_ConversationWithVisualizer, conversation)._visualizer


def _execution_status(state: ConversationStateProtocol | None) -> str | None:
    if state is None:
        return None
    return state.execution_status.value


def _ensure_agent_turn(
    turns: list[NotebookTurn],
    last_agent_turn: NotebookTurn | None,
    *,
    response_id: str | None,
) -> NotebookTurn:
    if (
        last_agent_turn is not None
        and last_agent_turn.role == "agent"
        and last_agent_turn.response_id == response_id
    ):
        return last_agent_turn

    turn = NotebookTurn(role="agent", response_id=response_id)
    turns.append(turn)
    return turn


def _ensure_tool_call(
    turns: list[NotebookTurn],
    pending_tool_calls: dict[str, NotebookToolCall],
    last_agent_turn: NotebookTurn | None,
    *,
    tool_call_id: str,
    tool_name: str,
) -> NotebookToolCall:
    existing = pending_tool_calls.get(tool_call_id)
    if existing is not None:
        return existing

    turn = _ensure_agent_turn(turns, last_agent_turn, response_id=None)
    tool_call = NotebookToolCall(tool_name=tool_name, tool_call_id=tool_call_id)
    turn.tool_calls.append(tool_call)
    pending_tool_calls[tool_call_id] = tool_call
    return tool_call


def _upsert_section(
    sections: list[NotebookSection],
    new_section: NotebookSection,
) -> None:
    for index, section in enumerate(sections):
        if section.title == new_section.title:
            sections[index] = new_section
            return
    sections.append(new_section)


def _banner_markdown(model: NotebookConversationModel) -> str:
    status = _normalize_status_value(model.execution_status)
    pending_tools = [
        tool_call.tool_name
        for turn in model.turns
        for tool_call in turn.tool_calls
        if tool_call.status == "pending"
    ]

    if status == "waiting_for_confirmation":
        pending = ", ".join(dict.fromkeys(pending_tools)) or "pending tool action"
        return (
            "### Approval required\n\n"
            f"Waiting for confirmation for **{pending}**."
        )

    if status == "paused":
        return "### Paused\n\nResume from the live controls below."

    if status in {"error", "stuck"}:
        label = _format_status_label(status)
        return f"### {label}\n\nReview the latest tool output below."

    return ""


def _tool_call_block(tool_call: NotebookToolCall) -> str:
    lines = [
        f"**Status:** {_tool_status_label(tool_call.status)}",
    ]
    if tool_call.summary:
        lines.extend(["", tool_call.summary])
    for section in tool_call.sections:
        lines.extend(["", f"**{section.title}**", "", _section_body(section)])
    return _details_block(
        f"Tool `{escape(tool_call.tool_name)}` · {_tool_status_label(tool_call.status)}",
        "\n".join(lines).strip(),
    )


def _section_body(section: NotebookSection) -> str:
    if section.kind == "code":
        return _code_fence(section.content)
    return section.content


def _details_block(summary: str, body: str) -> str:
    return (
        "<details>\n"
        f"<summary>{summary}</summary>\n\n"
        f"{body}\n\n"
        "</details>"
    )


def _message_event_text(event: MessageEvent) -> str:
    return "".join(content_to_str(event.to_llm_message().content)).strip()


def _message_reasoning_text(event: MessageEvent) -> str:
    parts: list[str] = []
    if event.reasoning_content:
        parts.append(event.reasoning_content.strip())

    reasoning_item = event.llm_message.responses_reasoning_item
    if reasoning_item is not None:
        if reasoning_item.summary:
            parts.extend(f"- {summary}" for summary in reasoning_item.summary)
        if reasoning_item.content:
            parts.extend(str(block) for block in reasoning_item.content)

    return "\n".join(part for part in parts if part).strip()


def _action_reasoning_text(event: ActionEvent) -> str:
    parts: list[str] = []
    if event.reasoning_content:
        parts.append(event.reasoning_content.strip())

    thought = _text_content_sequence_to_text(event.thought)
    if thought:
        parts.append(thought)

    reasoning_item = event.responses_reasoning_item
    if reasoning_item is not None:
        if reasoning_item.summary:
            parts.extend(f"- {summary}" for summary in reasoning_item.summary)
        if reasoning_item.content:
            parts.extend(str(block) for block in reasoning_item.content)

    return "\n\n".join(part for part in parts if part).strip()


def _security_risk_text(event: ActionEvent) -> str:
    if event.security_risk == risk.SecurityRisk.UNKNOWN:
        return ""
    return event.security_risk.visualize.plain.strip()


def _observation_text(event: ObservationEvent) -> str:
    return "".join(content_to_str(event.observation.to_llm_content)).strip()


def _text_content_sequence_to_text(content: Sequence[TextContent]) -> str:
    return "\n".join(text.text for text in content if text.text).strip()


def _event_visual_text(event: Event) -> str:
    return event.visualize.plain.strip()


def _stringify_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, sort_keys=True)
    except TypeError:
        return str(value)


def _acp_summary(event: ACPToolCallEvent) -> str | None:
    fragments: list[str] = []
    if event.tool_kind:
        fragments.append(f"kind={event.tool_kind}")
    if event.status:
        fragments.append(f"status={event.status}")
    if not fragments:
        return None
    return " · ".join(fragments)


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


def _code_fence(content: str) -> str:
    language = "json" if _looks_like_json(content) else "text"
    return f"```{language}\n{content}\n```"


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


def _tool_status_label(status: _ToolStatus) -> str:
    if status == "completed":
        return "Result"
    if status == "error":
        return "Error"
    if status == "rejected":
        return "Rejected"
    return "Pending"


def _normalize_status_value(status: str | None) -> str:
    if not status:
        return "idle"
    return status.strip().lower()


def _format_status_label(status: str) -> str:
    return status.replace("_", " ").title()
