from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from openhands.sdk import Agent as OpenHandsAgent
from openhands.sdk import Conversation
from openhands.sdk.conversation.base import BaseConversation
from openhands.tools import get_default_agent

from pyflow.context import Context
from pyflow.model import Model
from pyflow.request import Request
from pyflow.sink import RequestInput
from pyflow.utils import coerce_step


@dataclass(frozen=True, kw_only=True)
class Agent:
    """
    Pyflow runtime sink backed by a stored OpenHands agent.

    Attributes:
        model: Pyflow model used to build an OpenHands LLM.
        contexts: Contexts rendered globally before request steps.
        workspace: OpenHands workspace path for execution.
    """

    model: Model
    contexts: Sequence[Context] = ()
    workspace: str | Path = field(default_factory=Path.cwd)
    _openhands_agent: OpenHandsAgent = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """
        Build and store the OpenHands agent once at initialization.
        """
        object.__setattr__(
            self,
            "_openhands_agent",
            get_default_agent(
                llm=self.model.build_llm(),
                cli_mode=True,
            ),
        )

    def run(self, request: Request) -> BaseConversation:
        """
        Execute a request and return the OpenHands conversation.

        Args:
            request: Request to execute.

        Returns:
            OpenHands base conversation for this execution.
        """
        conversation = Conversation(
            agent=self._openhands_agent,
            workspace=self.workspace,
        )
        conversation.send_message(self._render_message(request))
        conversation.run()
        return conversation

    def __rrshift__(self, lhs: RequestInput) -> BaseConversation:
        """
        Execute request-like input via ``>>``.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            OpenHands base conversation for this execution.
        """
        return self.run(_coerce_request(lhs))

    def _render_message(self, request: Request) -> str:
        """
        Render a request with optional agent-level context preamble.

        Args:
            request: Request to render.

        Returns:
            Full prompt string sent to OpenHands.
        """
        rendered_request = request.render()
        if not self.contexts:
            return rendered_request

        lines = ["Context:"]
        for context in self.contexts:
            lines.append(f"- {context.render()}")
        lines.append("")
        lines.append(rendered_request)
        return "\n".join(lines)


def _coerce_request(value: RequestInput) -> Request:
    """
    Normalize request-like input into a ``Request``.

    Args:
        value: Request-like input (``Request`` or single-step input).

    Returns:
        Request representation of the provided input.
    """
    if isinstance(value, Request):
        return value
    return Request(steps=(coerce_step(value),))
