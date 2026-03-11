from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pyflow.request import Request
from pyflow.steps import StepInput

if TYPE_CHECKING:
    from openhands.sdk.conversation.base import BaseConversation


type RequestInput = Request | StepInput


class RequestSink(Protocol):
    """
    Protocol for objects that can consume requests via ``>>``.

    Implementations run a request and return the OpenHands conversation
    for post-run inspection.
    """

    def __rrshift__(self, lhs: RequestInput) -> BaseConversation:
        """
        Execute the left-hand request payload.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            The OpenHands conversation for this run.
        """
        ...
