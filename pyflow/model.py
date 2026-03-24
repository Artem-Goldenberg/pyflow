from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Self, Sequence

from openhands.sdk import LLM, Message
from openhands.sdk.llm.auth import SupportedVendor
from openhands.sdk.testing import TestLLM
from pydantic import SecretStr

from pyflow.session import Session
from pyflow.sink import RequestInput


def _validate_llm_constructor_kwargs(kwargs: dict[str, Any]) -> None:
    if "tool_choice" not in kwargs:
        return

    tool_choice = kwargs["tool_choice"]
    raise ValueError(
        "pyflow does not support configuring `tool_choice` on `Model`."
        f" Received `tool_choice={tool_choice!r}`. OpenHands forces "
        "`tool_choice='auto'` on the Responses API path and drops "
        "`tool_choice` entirely when `native_tool_calling=False`, so "
        "`tool_choice='required'` cannot be enforced here."
    )


@dataclass(kw_only=True)
class Model(ABC):
    """
    Abstract pyflow model that owns a live OpenHands ``LLM`` instance.
    """

    @property
    @abstractmethod
    def inner_llm(self) -> LLM:
        """
        Return the owned OpenHands ``LLM`` used for runtime execution.

        Returns:
            OpenHands LLM instance owned by this model.
        """

    @abstractmethod
    def _fresh_runtime_model(self) -> Self:
        """
        Return an isolated model instance for one runtime execution.

        Returns:
            Model instance with fresh runtime state suitable for one worker.
        """

    @staticmethod
    def from_api(
        *,
        name: str,
        api_key: SecretStr | None = None,
        base_url: str | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> AIModel:
        """
        Construct an API-backed model that owns a real OpenHands ``LLM``.

        Args:
            name: Provider-specific model identifier.
            api_key: Optional provider API key.
            base_url: Optional provider base URL.
            max_input_tokens: Optional input token limit.
            max_output_tokens: Optional output token limit.
            **kwargs: Additional OpenHands ``LLM`` kwargs.

        Returns:
            Pyflow model wrapper owning the configured OpenHands LLM.
        """
        _validate_llm_constructor_kwargs(kwargs)
        return AIModel(
            llm=_create_api_llm(
                name=name,
                api_key=api_key,
                base_url=base_url,
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                **kwargs,
            )
        )

    @staticmethod
    def subscription(
        *,
        vendor: SupportedVendor = "openai",
        model: str = "gpt-5.2-codex",
        force_login: bool = False,
        open_browser: bool = True,
        skip_consent: bool = False,
        **kwargs: Any,
    ) -> AIModel:
        """
        Construct a subscription-backed model that owns a live OpenHands ``LLM``.

        Args:
            vendor: Subscription vendor supported by OpenHands.
            model: Vendor model identifier.
            force_login: Whether to force fresh authentication.
            open_browser: Whether to open the browser for login.
            skip_consent: Whether to skip consent screens when supported.
            max_input_tokens: Optional input token limit.
            max_output_tokens: Optional output token limit.
            **kwargs: Additional OpenHands ``LLM`` kwargs.

        Returns:
            Pyflow model wrapper owning the authenticated OpenHands LLM.
        """
        _validate_llm_constructor_kwargs(kwargs)
        return AIModel(
            llm=LLM.subscription_login(
                vendor=vendor,
                model=model,
                force_login=force_login,
                open_browser=open_browser,
                skip_consent=skip_consent,
                # this is some bug with api, remove when fixed
                prompt_cache_retention=None, 
                **_default_llm_kwargs(**kwargs),
            )
        )

    @staticmethod
    def test(
        *,
        scripted_responses: Sequence[Message | Exception],
        name: str = "test-model",
        **kwargs: Any,
    ) -> TestModel:
        """
        Construct a test model that owns one live OpenHands ``TestLLM``.

        Args:
            scripted_responses: Ordered scripted responses or exceptions.
            name: Synthetic model name shown in metrics/events.
            **kwargs: Additional ``TestLLM.from_messages(...)`` kwargs.

        Returns:
            Pyflow test model wrapper owning the configured TestLLM.
        """
        scripted_responses_tuple = tuple(scripted_responses)
        return TestModel(
            llm=TestLLM.from_messages(
                messages=list(scripted_responses_tuple),
                model=name,
                **kwargs,
            ),
            scripted_responses=scripted_responses_tuple,
        )

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """
        Execute request-like input directly against this model via ``>>``.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            Pyflow session wrapper produced by the run.
        """
        from pyflow.agent import Agent

        return Agent(model=self).__rrshift__(lhs)


@dataclass(kw_only=True)
class AIModel(Model):
    """
    Pyflow wrapper around one live provider-backed OpenHands ``LLM``.
    """

    llm: LLM

    @property
    def inner_llm(self) -> LLM:
        """
        Return the owned provider-backed OpenHands ``LLM``.

        Returns:
            Owned OpenHands LLM instance.
        """
        return self.llm

    def _fresh_runtime_model(self) -> AIModel:
        llm = self.llm.model_copy()
        llm.reset_metrics()
        return AIModel(llm=llm)


@dataclass(kw_only=True)
class TestModel(Model):
    """
    Pyflow wrapper around one live OpenHands ``TestLLM`` plus the original script.
    """

    llm: TestLLM
    scripted_responses: Sequence[Message | Exception]

    @property
    def inner_llm(self) -> TestLLM:
        """
        Return the owned OpenHands ``TestLLM``.

        Returns:
            Owned OpenHands TestLLM instance.
        """
        return self.llm

    def __post_init__(self) -> None:
        self.scripted_responses = tuple(self.scripted_responses)

    def _fresh_runtime_model(self) -> TestModel:
        llm_data = self.llm.model_dump(mode="python")
        llm = TestLLM(
            **llm_data,
            scripted_responses=list(self.scripted_responses),
        )
        return TestModel(
            llm=llm,
            scripted_responses=self.scripted_responses,
        )


def _create_api_llm(
    *,
    name: str,
    api_key: SecretStr | None = None,
    base_url: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    **kwargs: Any,
) -> LLM:
    return LLM(
        model=name,
        api_key=api_key,
        base_url=base_url,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        **_default_llm_kwargs(**kwargs),
    )


def _default_llm_kwargs(**kwargs: Any) -> dict[str, Any]:
    return {
        "log_completions": True,
        "log_completions_folder": "logs/completions",
        **kwargs,
    }
