from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pyflow.context import Context
from pyflow.steps import Step, StepInput
from pyflow.utils import coerce_step, indent_multiline


@dataclass(frozen=True)
class Request:
    steps: Sequence[Step]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("Request.steps must be non-empty.")

    def __rshift__(self, rhs: StepInput) -> Request:
        return Request(steps=(*self.steps, coerce_step(rhs)))

    def __matmul__(self, attachment: Context) -> Request:
        first, rest = self.steps[0], self.steps[1:]
        return Request(steps=(first @ attachment, *rest))

    def render(self) -> str:
        lines: list[str] = []
        for index, step in enumerate(self.steps, start=1):
            prefix = f"{index}. "
            lines.extend(indent_multiline(prefix, step.render()))
        return "\n".join(lines)
