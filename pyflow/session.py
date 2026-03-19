from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.event.base import Event
from rich.console import Console, ConsoleOptions, RenderResult

from pyflow.display import (
    DisplayEnvironment,
    detect_display_environment,
    should_suppress_notebook_display,
    sync_interactive_session,
)
from pyflow.session_rendering import SessionTranscript, build_transcript
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
    _notebook_widget: NotebookSessionWidget | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def events(self) -> Sequence[Event]:
        """Recorded OpenHands events for this session, if available."""
        return tuple(self.conversation.state.events)

    @property
    def execution_status(self) -> str | None:
        """Current OpenHands execution status, if exposed by the conversation."""
        return self.conversation.state.execution_status.value

    @property
    def transcript(self) -> SessionTranscript:
        """Structured transcript built from the current event stream."""
        return build_transcript(
            self.events,
            execution_status=self.execution_status,
        )

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """Continue this session with request-like input via ``>>``."""
        request = convert_to_request(lhs)
        self.agent.append_message(self.conversation, request)
        self.conversation.run()
        sync_interactive_session(self)
        return self

    def render(self) -> str:
        """Render the session transcript as plain text."""
        return self.transcript.render_text()

    def render_html(self) -> str:
        """Render the session transcript as notebook-friendly HTML."""
        return self.transcript.render_html()

    def render_markdown(self) -> str:
        """Render the session transcript as notebook-friendly Markdown."""
        from pyflow.notebook_visualizer import notebook_markdown_for_session

        return notebook_markdown_for_session(self)

    def render_widget(self) -> object:
        """Render the session transcript as a read-only ipywidgets notebook view."""
        from pyflow.notebook_visualizer import notebook_widget_for_session

        return notebook_widget_for_session(self)

    def display(self, console: Console | None = None) -> None:
        """Render the session transcript with Rich."""
        self.transcript.display(console=console)

    def display_html(self) -> None:
        """Display the HTML transcript in IPython/Jupyter environments."""
        try:
            from IPython.display import HTML, display
        except ImportError as exc:
            raise RuntimeError("IPython is required for Session.display_html().") from exc

        display(HTML(self.render_html()))

    def display_markdown(self) -> None:
        """Display the Markdown transcript in IPython/Jupyter environments."""
        try:
            from IPython.display import display_markdown
        except ImportError as exc:
            raise RuntimeError(
                "IPython is required for Session.display_markdown()."
            ) from exc

        display_markdown(self.render_markdown(), raw=True)

    def _ipython_display_(self) -> None:
        """High-level IPython/Jupyter display hook."""
        if detect_display_environment() is not DisplayEnvironment.JUPYTER:
            return
        if should_suppress_notebook_display(self):
            return
        try:
            from IPython.display import display_markdown
        except ImportError as exc:
            raise RuntimeError("IPython is required for notebook display.") from exc

        display_markdown(self.render_markdown(), raw=True)

    def approve_pending_actions(self) -> Session:
        """Continue execution, approving any pending confirmation step."""
        self.conversation.run()
        sync_interactive_session(self)
        return self

    def reject_pending_actions(
        self,
        reason: str = "User rejected the action",
    ) -> Session:
        """Reject the current pending confirmation step."""
        self.conversation.reject_pending_actions(reason)
        sync_interactive_session(self)
        return self

    def pause(self) -> Session:
        """Pause the active conversation."""
        self.conversation.pause()
        sync_interactive_session(self)
        return self

    def __str__(self) -> str:
        """Plain-text transcript for non-Rich contexts."""
        return self.render()

    def __repr__(self) -> str:
        """Transcript representation for interactive Python sessions."""
        if (
            detect_display_environment() is DisplayEnvironment.JUPYTER
            and should_suppress_notebook_display(self)
        ):
            return ""
        if detect_display_environment().is_interactive:
            return self.render()
        return (
            f"{type(self).__name__}("
            f"agent={self.agent!r}, "
            f"conversation={self.conversation!r})"
        )

    def _repr_html_(self) -> str:
        """HTML representation used by IPython/Jupyter frontends."""
        if should_suppress_notebook_display(self):
            return ""
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            return ""
        return self.render_html()

    def _repr_markdown_(self) -> str:
        """Markdown representation used by IPython/Jupyter frontends."""
        if should_suppress_notebook_display(self):
            return ""
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            return self.render_markdown()
        return ""

    def _repr_mimebundle_(
        self,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Notebook MIME bundle used to suppress duplicate live output."""
        if should_suppress_notebook_display(self):
            return {}
        if detect_display_environment() is DisplayEnvironment.JUPYTER:
            from pyflow.notebook_visualizer import notebook_mimebundle_for_session

            return notebook_mimebundle_for_session(
                self,
                include=include,
                exclude=exclude,
            )
        return {
            "text/html": self.render_html(),
            "text/plain": self.render(),
        }

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        """Rich transcript rendering for ``console.print(session)``."""
        yield from self.transcript.__rich_console__(console, options)
