from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from pyflow.steps import Step, StepInput
from pyflow.utils import coerce_step


class Context(ABC):
    """Immutable attachment to a Step."""

    @abstractmethod
    def render(self) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.render()

    def __rmatmul__(self, payload: StepInput) -> Step:
        """Coerce the LHS into a Step and attach this Context."""
        return coerce_step(payload) @ self


@dataclass(frozen=True)
class DocsContext(Context):
    paths: Sequence[str]

    def render(self) -> str:
        joined = ", ".join(self.paths)
        return f"Use documentation files: {joined}."


@dataclass(frozen=True)
class CodeContext(Context):
    paths: Sequence[str]

    def render(self) -> str:
        joined = ", ".join(self.paths)
        return f"Use code files: {joined}."


def docs(*paths: str) -> DocsContext:
    return DocsContext(paths=paths)


def code(*paths: str) -> CodeContext:
    return CodeContext(paths=paths)
