from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from openhands.sdk.event import ObservationEvent
from openhands.sdk.llm import content_to_str
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from pyflow.request import Request
    from pyflow.session import Session


class SessionResultError(RuntimeError):
    """Base error raised while extracting a session result."""


class SessionResultMissingError(SessionResultError):
    """Raised when a session has no completed finish result."""


class SessionResultValidationError(SessionResultError):
    """Raised when a structured session result cannot be validated."""

    raw_text: str
    model_type: type[BaseModel]
    cause: Exception

    def __init__(
        self,
        *,
        raw_text: str,
        model_type: type[BaseModel],
        cause: Exception,
    ) -> None:
        self.raw_text = raw_text
        self.model_type = model_type
        self.cause = cause
        super().__init__(
            f"Session result does not match {model_type.__name__}: {cause}"
        )


@dataclass(frozen=True)
class OutputSpec[OutputModel: BaseModel]:
    """Structured output contract attached to a request."""

    model_type: type[OutputModel]

    def __post_init__(self) -> None:
        if not isinstance(self.model_type, type) or not issubclass(
            self.model_type,
            BaseModel,
        ):
            raise TypeError(
                "output(...) requires a pydantic.BaseModel subclass."
            )

    def __rfloordiv__(self, lhs: object) -> Request:
        from pyflow.request import Request
        from pyflow.steps import PromptStep, Step

        if isinstance(lhs, Request):
            return lhs // self
        if isinstance(lhs, str):
            return Request(steps=(PromptStep(text=lhs),), output_spec=self)
        if isinstance(lhs, PromptStep):
            return Request(steps=(lhs,), output_spec=self)
        if isinstance(lhs, Step):
            raise ValueError(
                "Output contracts may only be attached to the request root. "
                "Use 'prompt // output(Model) >> ...' or 'request // output(Model)'."
            )
        return NotImplemented

    def render(self) -> str:
        schema_text = json.dumps(
            self.model_type.model_json_schema(),
            indent=2,
            sort_keys=True,
        )
        lines = [
            "Output contract:",
            "Return the final answer by calling `finish`.",
            "Set `finish.message` to raw JSON that matches this schema exactly.",
            "Do not wrap the JSON in Markdown fences.",
            "Do not include extra prose outside the JSON.",
            "JSON schema:",
            schema_text,
        ]
        return "\n".join(lines)

    def parse_result(self, raw_text: str) -> OutputModel:
        try:
            return self.model_type.model_validate_json(raw_text)
        except ValidationError as exc:
            raise SessionResultValidationError(
                raw_text=raw_text,
                model_type=self.model_type,
                cause=exc,
            ) from exc


def output[OutputModel: BaseModel](
    model_type: type[OutputModel],
) -> OutputSpec[OutputModel]:
    """Declare a structured output contract for a request."""
    return OutputSpec(model_type=model_type)


def extract_session_result_text(session: Session) -> str:
    """Return the latest completed finish observation text for a session."""
    for event in reversed(session.events):
        if not isinstance(event, ObservationEvent):
            continue
        if event.tool_name != "finish":
            continue
        return "".join(content_to_str(event.observation.to_llm_content)).strip()
    raise SessionResultMissingError(
        "Session has no completed finish result to parse."
    )
