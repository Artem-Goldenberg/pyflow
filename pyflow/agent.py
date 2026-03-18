from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from openhands.sdk import Agent as OpenHandsAgent
from openhands.sdk import Conversation
from openhands.sdk.conversation.base import BaseConversation

from pyflow.context import Context
from pyflow.display import mark_live_repl_value
from pyflow.model import Model
from pyflow.request import Request
from pyflow.session import Session
from pyflow.sink import RequestInput
from pyflow.tooling import Tool, compile_openhands_tools, default_agent_tools
from pyflow.utils import convert_to_request


@dataclass(frozen=True, kw_only=True)
class Agent:
    """
    Pyflow runtime sink backed by a fresh OpenHands agent per run.

    Attributes:
        model: Pyflow model used to build an OpenHands LLM.
        contexts: Contexts rendered globally before request steps.
        tools: Tools attached to every run.
        workspace: OpenHands workspace path for execution.
    """

    model: Model
    contexts: Sequence[Context] = ()
    tools: Sequence[Tool] = field(default_factory=default_agent_tools)
    workspace: str | Path = field(default_factory=Path.cwd)

    def run(self, request: Request) -> Session:
        """
        Execute a request and return a pyflow session.

        Args:
            request: Request to execute.

        Returns:
            Pyflow session wrapper for this execution.
        """
        conversation = Conversation(
            agent=self._build_openhands_agent(),
            workspace=self.workspace,
        )
        self.append_message(conversation, request, include_global_context=True)
        conversation.run()
        session = Session(agent=self, conversation=conversation)
        mark_live_repl_value(session)
        return session

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """
        Execute request-like input via ``>>``.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            Pyflow session wrapper for this execution.
        """
        return self.run(convert_to_request(lhs))

    def append_message(
        self,
        conversation: BaseConversation,
        request: Request,
        *,
        include_global_context: bool = False,
    ) -> None:
        """Append a request message to an existing conversation."""
        message = request.render()
        if include_global_context:
            message = self._render_message(request)
        conversation.send_message(message)

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

    def _build_openhands_agent(self) -> OpenHandsAgent:
        tool_specs = compile_openhands_tools(self.tools)
        return OpenHandsAgent(
            llm=self.model.build_llm(),
            tools=list(tool_specs),
            system_prompt_kwargs={"cli_mode": True},
        )
