from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyflow.request import Request
    from pyflow.sink import RequestInput
    from pyflow.steps import Step, StepInput


def convert_to_step(value: StepInput) -> Step:
    """Internal helper for __rshift__ and Context.__rmatmul__."""
    from pyflow.steps import PromptStep, Step

    if isinstance(value, Step):
        return value
    if isinstance(value, str):
        return PromptStep(text=value)
    raise TypeError(f"Unsupported step input: {type(value)!r}")


def convert_to_request(value: RequestInput) -> Request:
    """Internal helper for sink execution of request-like payloads."""
    from pyflow.request import Request

    if isinstance(value, Request):
        return value
    return Request(steps=(convert_to_step(value),))


def indent_multiline(prefix: str, text: str) -> list[str]:
    lines = text.splitlines() or [""]
    output = [f"{prefix}{lines[0]}"]
    indent = " " * len(prefix)
    for line in lines[1:]:
        output.append(f"{indent}{line}")
    return output
