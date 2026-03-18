from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.event.base import Event
from rich.console import Console, ConsoleOptions, RenderResult

from pyflow.display import detect_display_environment, mark_live_repl_value
from pyflow.session_rendering import SessionTranscript, build_transcript
from pyflow.sink import RequestInput
from pyflow.utils import convert_to_request

if TYPE_CHECKING:
    from pyflow.agent import Agent


@dataclass(kw_only=True, repr=False)
class Session:
    """Pyflow runtime session wrapper around a live OpenHands conversation."""

    agent: Agent
    conversation: BaseConversation

    @property
    def events(self) -> Sequence[Event]:
        """Recorded OpenHands events for this session, if available."""
        return tuple(self.conversation.state.events)

    @property
    def transcript(self) -> SessionTranscript:
        """Structured transcript built from the current event stream."""
        return build_transcript(self.events)

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """Continue this session with request-like input via ``>>``."""
        request = convert_to_request(lhs)
        self.agent.append_message(self.conversation, request)
        self.conversation.run()
        mark_live_repl_value(self)
        return self

    def render(self) -> str:
        """Render the session transcript as plain text."""
        return self.transcript.render_text()

    def display(self, console: Console | None = None) -> None:
        """Render the session transcript with Rich."""
        self.transcript.display(console=console)

    def __str__(self) -> str:
        """Plain-text transcript for non-Rich contexts."""
        return self.render()

    def __repr__(self) -> str:
        """Transcript representation for interactive Python sessions."""
        if detect_display_environment().is_interactive:
            return self.render()
        return (
            f"{type(self).__name__}("
            f"agent={self.agent!r}, "
            f"conversation={self.conversation!r})"
        )

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        """Rich transcript rendering for ``console.print(session)``."""
        yield from self.transcript.__rich_console__(console, options)
