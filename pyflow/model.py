from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from openhands.sdk import LLM
from openhands.sdk.conversation.base import BaseConversation
from openhands.sdk.llm import Message
from openhands.sdk.testing import TestLLM
from pydantic import SecretStr

from pyflow.sink import RequestInput


@dataclass(frozen=True, kw_only=True)
class Model(ABC):
    """
    Abstract pyflow model that can construct an OpenHands ``LLM``.
    """

    @abstractmethod
    def build_llm(self) -> LLM:
        """
        Build the OpenHands ``LLM`` instance for runtime execution.

        Returns:
            Configured OpenHands LLM instance.
        """
        raise NotImplementedError

    def __rrshift__(self, lhs: RequestInput) -> BaseConversation:
        """
        Execute request-like input directly against this model via ``>>``.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            OpenHands conversation produced by the run.
        """
        from pyflow.agent import Agent

        return Agent(model=self).__rrshift__(lhs)


@dataclass(frozen=True, kw_only=True)
class AIModel(Model):
    """
    Provider-backed model configuration for OpenHands execution.

    Attributes:
        name: Provider-specific model identifier.
        base_url: Provider base URL.
        api_key: Provider API key.
    """

    name: str
    api_key: SecretStr
    base_url: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    def build_llm(self) -> LLM:
        """
        Build a real provider-backed OpenHands ``LLM``.

        Returns:
            OpenHands LLM configured for the target provider.
        """
        return LLM(
            model=self.name,
            api_key=self.api_key,
            base_url=self.base_url,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            log_completions=True,
            log_completions_folder="logs/completions"
        )


@dataclass(frozen=True, kw_only=True)
class TestModel(Model):
    """
    Scripted offline model backed by OpenHands ``TestLLM``.

    Attributes:
        scripted_responses: Ordered scripted responses or exceptions.
        name: Synthetic model name shown in metrics/events.
    """

    scripted_responses: Sequence[Message | Exception]
    name: str = "test-model"

    def build_llm(self) -> LLM:
        """
        Build a deterministic ``TestLLM`` from scripted responses.

        Returns:
            OpenHands TestLLM instance.
        """
        return TestLLM.from_messages(
            messages=list(self.scripted_responses),
            model=self.name,
        )
