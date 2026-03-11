from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence, TypeAlias

from pyflow.utils import coerce_step

if TYPE_CHECKING:
    from pyflow.context import Context
    from pyflow.request import Request
    from pyflow.sink import RequestSink


@dataclass(frozen=True, kw_only=True)
class Step(ABC):
    attachments: Sequence[Context] = ()

    @abstractmethod
    def render_base(self) -> str:
        raise NotImplementedError

    def render(self) -> str:
        base = self.render_base()
        if not self.attachments:
            return base
        rendered = " ".join(context.render() for context in self.attachments)
        return f"{base} {rendered}"

    def __matmul__(self, attachment: Context) -> Step:
        return dataclasses.replace(self, attachments=(*self.attachments, attachment))

    def __rshift__(self, rhs: StepInput | RequestSink) -> Request:
        from pyflow.request import Request

        if not isinstance(rhs, StepInput):
            return NotImplemented
        return Request(steps=(self, coerce_step(rhs)))

    def __rrshift__(self, lhs: StepInput) -> Request:
        from pyflow.request import Request

        return Request(steps=(coerce_step(lhs), self))


StepInput: TypeAlias = str | Step


@dataclass(frozen=True)
class PromptStep(Step):
    text: str

    def render_base(self) -> str:
        return self.text


@dataclass(frozen=True)
class TestStep(Step):
    names: Sequence[str]

    def render_base(self) -> str:
        joined = ", ".join(self.names)
        return f"Before finishing, ensure tests pass: {joined}."


def tests(*names: str) -> TestStep:
    return TestStep(names=names)
