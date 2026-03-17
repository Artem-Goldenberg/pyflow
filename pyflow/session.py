from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openhands.sdk.conversation.base import BaseConversation

from pyflow.sink import RequestInput
from pyflow.utils import convert_to_request

if TYPE_CHECKING:
    from pyflow.agent import Agent


@dataclass(kw_only=True)
class Session:
    """Pyflow runtime session wrapper around a live OpenHands conversation."""

    agent: Agent
    conversation: BaseConversation

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """Continue this session with request-like input via ``>>``."""
        request = convert_to_request(lhs)
        self.agent.append_message(self.conversation, request)
        self.conversation.run()
        return self
