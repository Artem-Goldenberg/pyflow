from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pyflow.request import Request
from pyflow.steps import StepInput

if TYPE_CHECKING:
    from pyflow.session import Session


type RequestInput = Request | StepInput


class RequestSink(Protocol):
    """Protocol for objects that can consume requests via ``>>``."""

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """Execute the left-hand request payload and return a pyflow session."""
        ...
