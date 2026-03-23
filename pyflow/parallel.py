from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pyflow.session import Session


@dataclass(frozen=True, kw_only=True)
class ParallelFailure[T]:
    """Inline failure entry returned from ``Agent.parallel(...)``."""

    index: int
    item: T
    phase: Literal["build_request", "run"]
    error: Exception
    session: Session | None
