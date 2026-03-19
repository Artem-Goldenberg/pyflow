from __future__ import annotations

import json

from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING, Callable, Literal, Protocol, Sequence, cast

import ipywidgets as widgets
from IPython.display import Markdown, display
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
    def display(self, widget: widgets.Widget) -> None: ...


class _ConversationWithVisualizer(Protocol):
    _visualizer: ConversationVisualizerBase | None


class NotebookConversationVisualizer(ConversationVisualizerBase):
    """Notebook visualizer backed by a persistent ipywidgets view."""

    _display_target: NotebookDisplayTarget | None
    _events: list[Event]
    _seeded_from_state: bool
    _session_widget: NotebookSessionWidget

    def __init__(
        self,
        *,
        display_target: NotebookDisplayTarget | None = None,
        session_widget: NotebookSessionWidget | None = None,
    ) -> None:
        super().__init__()
        self._display_target = (
            display_target if display_target is not None else _IPythonWidgetTarget()
        )
        self._session_widget = (
            session_widget if session_widget is not None else NotebookSessionWidget()
        )
        self._events = []
        self._seeded_from_state = False

    @property
    def widget(self) -> widgets.Widget:
        return self._session_widget.widget

    def bind_session(self, session: Session) -> None:
        self._session_widget.bind_session(session)

    def on_event(self, event: Event) -> None:
        self._seed_events_from_state()
        self._events.append(event)
        self.refresh()

    def refresh(self) -> None:
        """Refresh the live notebook widget from current conversation state."""
        model = build_notebook_conversation_model(
            self._current_events(),
            execution_status=_execution_status(self._state),
        )
        self._session_widget.render(model)
        if self._display_target is not None:
            self._display_target.display(self._session_widget.widget)

    def _seed_events_from_state(self) -> None:
        if self._seeded_from_state or self._state is None:
            return
        self._events = list(self._state.events)
        self._seeded_from_state = True

    def _current_events(self) -> list[Event]:
        if self._state is None:
            return list(self._events)
        return list(self._state.events)


class NotebookSessionWidget:
    """Reusable widget tree for live notebook visualization and session display."""

    _session: Session | None
    _model: NotebookConversationModel | None
    _style: widgets.HTML
    _title: widgets.HTML
    _status: widgets.HTML
    _banner: widgets.HTML
    _transcript: widgets.VBox
    _composer: widgets.Textarea
    _send_button: widgets.Button
    _approve_button: widgets.Button
    _reject_button: widgets.Button
    _feedback: widgets.HTML
    _widget: widgets.VBox

    def __init__(self) -> None:
        self._session = None
        self._model = None
        self._style = widgets.HTML(_NOTEBOOK_WIDGET_STYLE)
        self._title = widgets.HTML()
        self._status = widgets.HTML()
        self._banner = widgets.HTML()
        self._banner.layout.display = "none"
        self._transcript = widgets.VBox()
        self._transcript.add_class("pyflow-notebook__stack")
        self._composer = widgets.Textarea(
            placeholder="Continue the conversation…",
            rows=3,
            layout=widgets.Layout(width="100%"),
        )
        self._composer.add_class("pyflow-notebook__textarea")
        self._send_button = widgets.Button(
            description="Send",
            button_style="primary",
            icon="paper-plane",
        )
        self._approve_button = widgets.Button(
            description="Approve",
            button_style="success",
            icon="check",
        )
        self._reject_button = widgets.Button(
            description="Reject",
            button_style="danger",
            icon="times",
        )
        self._feedback = widgets.HTML()
        self._feedback.layout.display = "none"

        self._send_button.on_click(self._on_send)
        self._approve_button.on_click(self._on_approve)
        self._reject_button.on_click(self._on_reject)

        header = widgets.HBox(
            [self._title, self._status],
            layout=widgets.Layout(
                width="100%",
                justify_content="space-between",
                align_items="flex-start",
            ),
        )
        header.add_class("pyflow-notebook__header")

        controls = widgets.HBox(
            [self._send_button, self._approve_button, self._reject_button],
            layout=widgets.Layout(flex_flow="row wrap"),
        )
        controls.add_class("pyflow-notebook__controls")

        composer_box = widgets.VBox(
            [
                widgets.HTML(
                    '<div class="pyflow-notebook__composer-label">'
                    "Continue This Session"
                    "</div>"
                ),
                self._composer,
                controls,
                self._feedback,
            ],
        )
        composer_box.add_class("pyflow-notebook__composer")
        composer_box.add_class("pyflow-notebook__stack")

        self._widget = widgets.VBox(
            [
                self._style,
                header,
                self._banner,
                self._transcript,
                composer_box,
            ],
            layout=widgets.Layout(width="100%"),
        )
        self._widget.add_class("pyflow-notebook")
        self._widget.add_class("pyflow-notebook__stack")

    @property
    def widget(self) -> widgets.Widget:
        return self._widget

    def bind_session(self, session: Session) -> None:
        self._session = session

    def render(self, model: NotebookConversationModel) -> None:
        self._model = model
        self._title.value = _header_markup(model)
        self._status.value = _status_badge_markup(model.execution_status)
        banner_markup = _banner_markup(model)
        if banner_markup:
            self._banner.value = banner_markup
            self._banner.layout.display = ""
        else:
            self._banner.value = ""
            self._banner.layout.display = "none"

        self._transcript.children = tuple(_turn_widget(turn) for turn in model.turns) or (
            widgets.HTML(
                '<div class="pyflow-notebook__empty">'
                "Session has no recorded events."
                "</div>"
            ),
        )
        self._update_controls(model.execution_status)

    def mimebundle(self, *, text_plain: str) -> dict[str, object]:
        bundle = cast(dict[str, object], self._widget._repr_mimebundle_())
        bundle["text/plain"] = text_plain
        return bundle

    def _on_send(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("The session is not attached to this widget yet.")
            return

        session = self._session
        prompt = self._composer.value.strip()
        if not prompt:
            self._set_feedback("Enter a message before sending.")
            return

        self._run_session_action(lambda: prompt >> session)
        self._composer.value = ""

    def _on_approve(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("The session is not attached to this widget yet.")
            return

        session = self._session
        self._run_session_action(session.approve_pending_actions)

    def _on_reject(self, _: widgets.Button) -> None:
        if self._session is None:
            self._set_feedback("The session is not attached to this widget yet.")
            return

        session = self._session
        reason = self._composer.value.strip() or "User rejected the action"
        self._run_session_action(lambda: session.reject_pending_actions(reason))
        if self._composer.value.strip():
            self._composer.value = ""

    def _run_session_action(self, action: Callable[[], object]) -> None:
        self._set_feedback("Running…", pending=True)
        self._set_busy(True)
        try:
            action()
            self._clear_feedback()
        except Exception as exc:
            self._set_feedback(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if self._model is not None:
                self._update_controls(self._model.execution_status)

    def _set_busy(self, is_busy: bool) -> None:
        self._send_button.disabled = is_busy
        self._approve_button.disabled = is_busy
        self._reject_button.disabled = is_busy
        self._composer.disabled = is_busy

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

    def _set_feedback(self, message: str, *, pending: bool = False) -> None:
        feedback_class = (
            "pyflow-notebook__feedback pyflow-notebook__feedback--pending"
            if pending
            else "pyflow-notebook__feedback"
        )
        self._feedback.value = (
            f'<div class="{feedback_class}">{escape(message)}</div>'
        )
        self._feedback.layout.display = ""

    def _clear_feedback(self) -> None:
        self._feedback.value = ""
        self._feedback.layout.display = "none"


class _IPythonWidgetTarget:
    _displayed: bool

    def __init__(self) -> None:
        self._displayed = False

    def display(self, widget: widgets.Widget) -> None:
        if self._displayed:
            return
        display(widget)
        self._displayed = True


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


def notebook_widget_for_session(session: Session) -> widgets.Widget:
    widget = _session_widget_for_session(session)
    widget.render(
        build_notebook_conversation_model(
            session.events,
            execution_status=session.execution_status,
        )
    )
    return widget.widget


def notebook_mimebundle_for_session(
    session: Session,
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> dict[str, object]:
    del include, exclude
    widget = _session_widget_for_session(session)
    widget.render(
        build_notebook_conversation_model(
            session.events,
            execution_status=session.execution_status,
        )
    )
    return widget.mimebundle(text_plain=session.render())


def sync_notebook_session(session: Session) -> None:
    widget = _session_widget_for_session(session)
    widget.bind_session(session)
    widget.render(
        build_notebook_conversation_model(
            session.events,
            execution_status=session.execution_status,
        )
    )


def _session_widget_for_session(session: Session) -> NotebookSessionWidget:
    visualizer = _conversation_visualizer(session.conversation)
    if isinstance(visualizer, NotebookConversationVisualizer):
        visualizer.bind_session(session)
        return visualizer._session_widget

    if session._notebook_widget is None:
        session._notebook_widget = NotebookSessionWidget()
    session._notebook_widget.bind_session(session)
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


def _turn_widget(turn: NotebookTurn) -> widgets.Widget:
    bubble_children: list[widgets.Widget] = []

    if turn.messages:
        bubble_children.extend(_markdown_block(message) for message in turn.messages)

    if turn.sections:
        detail_box = widgets.VBox(
            [_section_widget(section) for section in turn.sections],
        )
        detail_box.add_class("pyflow-notebook__stack")
        details = widgets.Accordion(children=[detail_box], selected_index=None)
        details.set_title(0, "Details")
        details.add_class("pyflow-notebook__accordion")
        bubble_children.append(details)

    for tool_call in turn.tool_calls:
        bubble_children.append(_tool_call_widget(tool_call))

    if not bubble_children:
        bubble_children.append(
            widgets.HTML('<div class="pyflow-notebook__empty-turn">[empty]</div>')
        )

    bubble = widgets.VBox(bubble_children)
    bubble.add_class("pyflow-notebook__bubble")
    bubble.add_class(f"pyflow-notebook__bubble--{turn.role}")
    bubble.add_class("pyflow-notebook__stack")

    row = widgets.HBox(
        [bubble],
        layout=widgets.Layout(
            width="100%",
            justify_content="flex-end" if turn.role == "user" else "flex-start",
        ),
    )
    row.add_class("pyflow-notebook__row")
    row.add_class(f"pyflow-notebook__row--{turn.role}")
    return row


def _tool_call_widget(tool_call: NotebookToolCall) -> widgets.Widget:
    details_children: list[widgets.Widget] = []
    summary_markup = _tool_summary_markup(tool_call)
    if summary_markup:
        details_children.append(widgets.HTML(summary_markup))

    details_children.extend(_section_widget(section) for section in tool_call.sections)
    if not details_children:
        details_children.append(
            widgets.HTML(
                '<div class="pyflow-notebook__tool-hint">'
                "Awaiting approval or execution."
                "</div>"
            )
        )

    detail_box = widgets.VBox(details_children)
    detail_box.add_class("pyflow-notebook__tool-body")
    detail_box.add_class("pyflow-notebook__stack")

    accordion = widgets.Accordion(children=[detail_box], selected_index=None)
    accordion.set_title(0, _tool_title(tool_call))
    accordion.add_class("pyflow-notebook__tool")
    return accordion


def _section_widget(section: NotebookSection) -> widgets.Widget:
    title = widgets.HTML(
        '<div class="pyflow-notebook__section-title">'
        f"{escape(section.title)}"
        "</div>"
    )
    content = (
        _markdown_block(section.content)
        if section.kind == "markdown"
        else _code_block(section.content)
    )
    section_box = widgets.VBox([title, content])
    section_box.add_class("pyflow-notebook__section")
    section_box.add_class("pyflow-notebook__stack")
    return section_box


def _markdown_block(content: str) -> widgets.Output:
    output = widgets.Output()
    output.add_class("pyflow-notebook__markdown")
    with output:
        display(Markdown(content))
    return output


def _code_block(content: str) -> widgets.Output:
    output = widgets.Output()
    output.add_class("pyflow-notebook__code")
    language = "json" if _looks_like_json(content) else "text"
    with output:
        display(Markdown(f"```{language}\n{content}\n```"))
    return output


def _header_markup(model: NotebookConversationModel) -> str:
    tool_count = sum(len(turn.tool_calls) for turn in model.turns)
    summary = (
        f"{len(model.turns)} turn{'s' if len(model.turns) != 1 else ''}"
        f" · {tool_count} tool call{'s' if tool_count != 1 else ''}"
    )
    return (
        '<div class="pyflow-notebook__eyebrow">pyflow session</div>'
        '<div class="pyflow-notebook__title">Conversation Transcript</div>'
        f'<div class="pyflow-notebook__summary">{escape(summary)}</div>'
    )


def _status_badge_markup(execution_status: str | None) -> str:
    status = _normalize_status_value(execution_status)
    return (
        '<div class="pyflow-notebook__status '
        f'pyflow-notebook__status--{escape(status)}">'
        f"{escape(_format_status_label(status))}"
        "</div>"
    )


def _banner_markup(model: NotebookConversationModel) -> str:
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
            '<div class="pyflow-notebook__banner pyflow-notebook__banner--pending">'
            "<strong>Approval required.</strong> "
            f"Waiting for confirmation for {escape(pending)}."
            "</div>"
        )

    if status == "paused":
        return (
            '<div class="pyflow-notebook__banner pyflow-notebook__banner--paused">'
            "<strong>Paused.</strong> Resume from the controls below."
            "</div>"
        )

    if status in {"error", "stuck"}:
        return (
            '<div class="pyflow-notebook__banner pyflow-notebook__banner--error">'
            f"<strong>{escape(_format_status_label(status))}.</strong> "
            "Review the latest tool output below."
            "</div>"
        )

    return ""


def _tool_title(tool_call: NotebookToolCall) -> str:
    title = f"{tool_call.tool_name} · {_tool_status_label(tool_call.status)}"
    if tool_call.summary:
        title = f"{title} · {tool_call.summary}"
    if len(title) > 88:
        return title[:85] + "..."
    return title


def _tool_summary_markup(tool_call: NotebookToolCall) -> str:
    if tool_call.summary is None:
        return ""
    return (
        '<div class="pyflow-notebook__tool-summary">'
        f"{escape(tool_call.summary)}"
        "</div>"
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
    visualize = event.visualize
    return visualize.plain.strip()


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


def _looks_like_json(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    return stripped[0] in ("{", "[")


def _format_jsonish(content: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content
    return json.dumps(parsed, indent=2, sort_keys=True)


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


_NOTEBOOK_WIDGET_STYLE = """
<style>
.pyflow-notebook {
  --pyflow-ink: #172033;
  --pyflow-muted: #5f6b7a;
  --pyflow-line: rgba(24, 37, 62, 0.12);
  --pyflow-surface: rgba(255, 255, 255, 0.92);
  --pyflow-surface-strong: rgba(255, 255, 255, 0.98);
  --pyflow-user: linear-gradient(135deg, #d9efff 0%, #edf7ff 100%);
  --pyflow-agent: linear-gradient(145deg, #fffdf8 0%, #ffffff 100%);
  --pyflow-system: linear-gradient(145deg, #fff5df 0%, #fffdf8 100%);
  background:
    radial-gradient(circle at top left, rgba(73, 173, 255, 0.16), transparent 32%),
    radial-gradient(circle at top right, rgba(255, 173, 96, 0.18), transparent 28%),
    linear-gradient(180deg, #f5f8ff 0%, #fbfcff 100%);
  border: 1px solid rgba(88, 99, 119, 0.16);
  border-radius: 24px;
  box-shadow: 0 18px 40px rgba(19, 34, 58, 0.08);
  color: var(--pyflow-ink);
  padding: 20px;
}
.pyflow-notebook__eyebrow {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--pyflow-muted);
  margin-bottom: 4px;
}
.pyflow-notebook__title {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
}
.pyflow-notebook__summary {
  color: var(--pyflow-muted);
  font-size: 13px;
  margin-top: 6px;
}
.pyflow-notebook__status {
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 700;
  background: rgba(34, 197, 94, 0.14);
  color: #166534;
}
.pyflow-notebook__status--waiting_for_confirmation {
  background: rgba(245, 158, 11, 0.14);
  color: #9a6700;
}
.pyflow-notebook__status--paused {
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}
.pyflow-notebook__status--error,
.pyflow-notebook__status--stuck {
  background: rgba(239, 68, 68, 0.12);
  color: #b42318;
}
.pyflow-notebook__banner {
  border-radius: 16px;
  padding: 12px 14px;
  border: 1px solid var(--pyflow-line);
  background: rgba(255, 255, 255, 0.76);
}
.pyflow-notebook__banner--pending {
  background: rgba(255, 244, 222, 0.88);
  border-color: rgba(217, 119, 6, 0.18);
}
.pyflow-notebook__banner--paused {
  background: rgba(224, 240, 255, 0.84);
  border-color: rgba(37, 99, 235, 0.16);
}
.pyflow-notebook__banner--error {
  background: rgba(255, 233, 233, 0.84);
  border-color: rgba(220, 38, 38, 0.16);
}
.pyflow-notebook__bubble {
  width: min(100%, 860px);
  border: 1px solid var(--pyflow-line);
  border-radius: 18px;
  padding: 14px;
  box-shadow: 0 10px 24px rgba(19, 34, 58, 0.05);
}
.pyflow-notebook__stack {
  gap: 12px;
}
.pyflow-notebook__bubble--user {
  background: var(--pyflow-user);
}
.pyflow-notebook__bubble--agent {
  background: var(--pyflow-agent);
}
.pyflow-notebook__bubble--system {
  background: var(--pyflow-system);
}
.pyflow-notebook__section-title,
.pyflow-notebook__composer-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--pyflow-muted);
}
.pyflow-notebook__tool-summary {
  color: var(--pyflow-ink);
  line-height: 1.5;
}
.pyflow-notebook__tool-hint,
.pyflow-notebook__empty,
.pyflow-notebook__empty-turn {
  color: var(--pyflow-muted);
}
.pyflow-notebook__composer {
  border-top: 1px solid var(--pyflow-line);
  padding-top: 14px;
}
.pyflow-notebook__controls {
  gap: 10px;
}
.pyflow-notebook__section {
  gap: 6px;
}
.pyflow-notebook__feedback {
  color: var(--pyflow-muted);
}
.pyflow-notebook__feedback--pending {
  color: #1d4ed8;
}
</style>
"""
