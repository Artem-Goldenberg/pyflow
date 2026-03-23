from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence, overload

from pydantic import BaseModel

from pyflow.context import Context
from pyflow.output import OutputSpec
from pyflow.steps import Step, StepInput
from pyflow.utils import convert_to_step, indent_multiline

if TYPE_CHECKING:
    from pyflow.session import Session
    from pyflow.sink import RequestSink


@dataclass(frozen=True)
class Request:
    steps: Sequence[Step]
    output_spec: OutputSpec[BaseModel] | None = None

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("Request.steps must be non-empty.")

    @overload
    def __rshift__(self, rhs: StepInput) -> Request: ...

    @overload
    def __rshift__(self, rhs: RequestSink) -> Session: ...

    def __rshift__(self, rhs: object) -> Request | Session:
        if not isinstance(rhs, StepInput):
            return NotImplemented
        return Request(
            steps=(*self.steps, convert_to_step(rhs)),
            output_spec=self.output_spec,
        )

    def __matmul__(self, attachment: Context) -> Request:
        first, rest = self.steps[0], self.steps[1:]
        return Request(
            steps=(first @ attachment, *rest),
            output_spec=self.output_spec,
        )

    def __floordiv__(self, rhs: object) -> Request:
        if not isinstance(rhs, OutputSpec):
            return NotImplemented
        if self.output_spec is not None:
            raise ValueError("Request already has an output contract.")
        return Request(steps=self.steps, output_spec=rhs)

    def render(self) -> str:
        lines: list[str] = []
        for index, step in enumerate(self.steps, start=1):
            prefix = f"{index}. "
            lines.extend(indent_multiline(prefix, step.render()))
        if self.output_spec is not None:
            lines.append("")
            lines.extend(self.output_spec.render().splitlines())
        return "\n".join(lines)
