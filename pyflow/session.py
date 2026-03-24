from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from openhands.sdk import BaseConversation, Event
from pydantic import BaseModel
from openhands.sdk import BaseConversation, ConversationStats, Event
from openhands.sdk.llm.utils.metrics import Metrics, TokenUsage
from rich.console import Console, ConsoleOptions, RenderResult

from pyflow.display import (
    DisplayEnvironment,
    _stdout_is_tty,
    detect_display_environment,
    prepare_live_render,
    should_suppress_live_inspection,
    sync_interactive_session,
)
from pyflow.output import OutputSpec, extract_session_result_text
from pyflow.session_rendering import (
    SessionTranscript,
    _SessionRenderView,
    build_transcript,
)
from pyflow.sink import RequestInput
from pyflow.utils import convert_to_request

if TYPE_CHECKING:
    from pyflow.agent import Agent
    from pyflow.notebook_visualizer import NotebookSessionWidget


@dataclass(kw_only=True, repr=False)
class Session:
    """Pyflow runtime session wrapper around a live OpenHands conversation."""

    agent: Agent
    conversation: BaseConversation
    output_spec: OutputSpec[BaseModel] | None = None
    _notebook_widget: NotebookSessionWidget | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _cached_result: BaseModel | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _cached_result_event_count: int = field(
        default=-1,
        init=False,
        repr=False,
    )

    @property
    def events(self) -> Sequence[Event]:
        """Recorded OpenHands events for this session, if available."""
        state = getattr(self.conversation, "state", None)
        events = getattr(state, "events", ())
        return tuple(events)

    @property
    def execution_status(self) -> str | None:
        """Current OpenHands execution status, if exposed by the conversation."""
        state = getattr(self.conversation, "state", None)
        execution_status = getattr(state, "execution_status", None)
        return getattr(execution_status, "value", None)

    @property
    def conversation_stats(self) -> ConversationStats:
        """Aggregated OpenHands conversation stats for this session."""
        return self.conversation.conversation_stats

    @property
    def metrics(self) -> Metrics:
        """Combined LLM metrics accumulated during this session."""
        return self.conversation_stats.get_combined_metrics()

    @property
    def token_usage(self) -> TokenUsage:
        """Aggregated token usage accumulated during this session."""
        token_usage = self.metrics.accumulated_token_usage
        if token_usage is None:
            raise RuntimeError("Session metrics did not expose accumulated token usage.")
        return token_usage

    @property
    def transcript(self) -> SessionTranscript:
        """Structured transcript built from the current event stream."""
        return self._build_transcript(view=_SessionRenderView.LIVE)

    @property
    def result_text(self) -> str:
        """Raw text returned by the latest completed finish observation."""
        return extract_session_result_text(self)

    @property
    def result(self) -> BaseModel | str:
        """Return either the parsed structured result or the raw finish text."""
        if self.output_spec is None:
            return self.result_text

        event_count = len(self.events)
        if self._cached_result is not None and self._cached_result_event_count == event_count:
            return self._cached_result

        parsed_result = self.output_spec.parse_result(self.result_text)
        self._cached_result = parsed_result
        self._cached_result_event_count = event_count
        return parsed_result

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """Continue this session with request-like input via ``>>``."""
        request = convert_to_request(lhs)
        if request.output_spec is not None:
            raise ValueError(
                "Structured output is only supported on fresh runs, not session continuations."
            )
        start_event_index = len(self.events)
        self._clear_output_state()
        self.agent.append_message(self.conversation, request)
        prepare_live_render(self.conversation, start_event_index=start_event_index)
        self.conversation.run()
        sync_interactive_session(self, start_event_index=start_event_index)
        return self

    def render(self) -> str:
        """Render the session transcript as plain text."""
        return self.transcript.render_text()

    def render_markdown(self) -> str:
        """Render the session transcript as notebook-friendly Markdown."""
        from pyflow.notebook_visualizer import notebook_markdown_for_session

        return notebook_markdown_for_session(self)

    def render_full(self) -> str:
        """Render the full session transcript as plain text."""
        return self._build_transcript(view=_SessionRenderView.FULL).render_text()

    def render_full_markdown(self) -> str:
        """Render the full session transcript as notebook-friendly Markdown."""
        from pyflow.notebook_visualizer import notebook_full_markdown_for_session

        return notebook_full_markdown_for_session(self)

    def render_widget(self) -> object:
        """Render the session transcript as a read-only ipywidgets notebook view."""
        from pyflow.notebook_visualizer import notebook_widget_for_session

        return notebook_widget_for_session(self)

    def display(self, console: Console | None = None) -> None:
        """Render the session transcript with Rich."""
        self._build_transcript(view=_SessionRenderView.FULL).display(console=console)

    def display_markdown(self) -> None:
        """Display the Markdown transcript in IPython/Jupyter environments."""
        try:
            from IPython.display import display_markdown
        except ImportError as exc:
            raise RuntimeError(
                "IPython is required for Session.display_markdown()."
            ) from exc

        display_markdown(self.render_full_markdown(), raw=True)

    def _ipython_display_(self) -> None:
        """High-level IPython/Jupyter display hook."""
        if detect_display_environment() is not DisplayEnvironment.JUPYTER:
            return
        if should_suppress_live_inspection(self):
            return
        try:
            from IPython.display import display_markdown
        except ImportError as exc:
            raise RuntimeError("IPython is required for notebook display.") from exc

        display_markdown(self.render_full_markdown(), raw=True)

    def approve_pending_actions(self) -> Session:
        """Continue execution, approving any pending confirmation step."""
        start_event_index = len(self.events)
        prepare_live_render(self.conversation, start_event_index=start_event_index)
        self.conversation.run()
        sync_interactive_session(self, start_event_index=start_event_index)
        return self

    def reject_pending_actions(
        self,
        reason: str = "User rejected the action",
    ) -> Session:
        """Reject the current pending confirmation step."""
        start_event_index = len(self.events)
        prepare_live_render(self.conversation, start_event_index=start_event_index)
        self.conversation.reject_pending_actions(reason)
        sync_interactive_session(self, start_event_index=start_event_index)
        return self

    def pause(self) -> Session:
        """Pause the active conversation."""
        start_event_index = len(self.events)
        prepare_live_render(self.conversation, start_event_index=start_event_index)
        self.conversation.pause()
        sync_interactive_session(self, start_event_index=start_event_index)
        return self

    def __str__(self) -> str:
        """Inspection-friendly string form for terminal or notebook use."""
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            return self.render_full_markdown()
        if _stdout_is_tty():
            console = Console(record=True, force_terminal=True, width=100)
            console.print(self._build_transcript(view=_SessionRenderView.FULL))
            return console.export_text(styles=True).rstrip("\n")
        return self.render_full()

    def __repr__(self) -> str:
        """Transcript representation for interactive Python sessions."""
        if should_suppress_live_inspection(self):
            return ""
        if detect_display_environment().is_interactive:
            return self.render_full()
        return (
            f"{type(self).__name__}("
            f"agent={self.agent!r}, "
            f"conversation={self.conversation!r})"
        )

    def _repr_markdown_(self) -> str:
        """Markdown representation used by IPython/Jupyter frontends."""
        if should_suppress_live_inspection(self):
            return ""
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            return self.render_full_markdown()
        return ""

    def _repr_mimebundle_(
        self,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Notebook MIME bundle used to suppress duplicate live output."""
        if should_suppress_live_inspection(self):
            return {}
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            from pyflow.notebook_visualizer import notebook_mimebundle_for_session

            return notebook_mimebundle_for_session(
                self,
                include=include,
                exclude=exclude,
            )
        return {"text/plain": self.render_full()}

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        """Rich transcript rendering for ``console.print(session)``."""
        yield from self._build_transcript(view=_SessionRenderView.FULL).__rich_console__(
            console,
            options,
        )

    def _build_transcript(
        self,
        *,
        view: _SessionRenderView,
    ) -> SessionTranscript:
        return build_transcript(
            self.events,
            execution_status=self.execution_status,
            view=view,
        )

    def _clear_output_state(self) -> None:
        self.output_spec = None
        self._cached_result = None
        self._cached_result_event_count = -1
