from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from openhands.sdk import Agent as OpenHandsAgent
from openhands.sdk import Conversation
from openhands.sdk.conversation.base import BaseConversation

from pyflow.context import Context
from pyflow.model import Model
from pyflow.request import Request
from pyflow.sink import RequestInput
from pyflow.tooling import (
    Tool,
    collect_request_tools,
    compile_openhands_tools,
    default_agent_tools,
)
from pyflow.utils import coerce_step


@dataclass(frozen=True, kw_only=True)
class Agent:
    """
    Pyflow runtime sink backed by a fresh OpenHands agent per run.

    Attributes:
        model: Pyflow model used to build an OpenHands LLM.
        contexts: Contexts rendered globally before request steps.
        tools: Tools attached to every run unless overridden by the request.
        workspace: OpenHands workspace path for execution.
    """

    model: Model
    contexts: Sequence[Context] = ()
    tools: Sequence[Tool] = field(default_factory=default_agent_tools)
    workspace: str | Path = field(default_factory=Path.cwd)

    def run(self, request: Request) -> BaseConversation:
        """
        Execute a request and return the OpenHands conversation.

        Args:
            request: Request to execute.

        Returns:
            OpenHands base conversation for this execution.
        """
        conversation = Conversation(
            agent=self._build_openhands_agent(request),
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

    def _build_openhands_agent(self, request: Request) -> OpenHandsAgent:
        tool_specs = compile_openhands_tools(self.tools, collect_request_tools(request))
        return OpenHandsAgent(
            llm=self.model.build_llm(),
            tools=list(tool_specs),
            system_prompt_kwargs={"cli_mode": True},
        )


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
