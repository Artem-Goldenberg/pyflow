from __future__ import annotations

import asyncio
import dataclasses
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Callable, cast, Sequence

from openhands.sdk import (
    Agent as OpenHandsAgent,
    BaseConversation,
    Conversation,
    Tool as OpenHandsToolSpec,
)

from pyflow.context import Context
from pyflow.display import (
    conversation_visualizer_for_environment,
    prepare_live_render,
    sync_interactive_session,
)
from pyflow.model import Model
from pyflow.parallel import ParallelFailure
from pyflow.request import Request
from pyflow.runtime_logging import apply_default_backend_log_policy
from pyflow.session import Session
from pyflow.sink import RequestInput
from pyflow.tooling import Tool, compile_openhands_tools, default_agent_tools
from pyflow.utils import convert_to_request


DEFAULT_SYSTEM_PROMPT = cast(
    str, OpenHandsAgent.model_fields["system_prompt_filename"].default,
)


@dataclass(frozen=True, kw_only=True)
class Agent:
    """
    Pyflow runtime sink backed by a fresh OpenHands agent per run.

    Attributes:
        model: Pyflow model that owns the OpenHands LLM used for execution.
        contexts: Contexts rendered globally before request steps.
        tools: Tools attached to every run.
        system_prompt: OpenHands system prompt template filename or absolute path.
        workspace: OpenHands workspace path for execution.
    """

    model: Model
    contexts: Sequence[Context] = ()
    tools: Sequence[Tool] = field(default_factory=default_agent_tools)
    system_prompt: str | Path = DEFAULT_SYSTEM_PROMPT
    workspace: str | Path = field(default_factory=Path.cwd)

    def replacing(
        self,
        *,
        model: Model | None = None,
        contexts: Sequence[Context] | None = None,
        tools: Sequence[Tool] | None = None,
        system_prompt: str | Path | None = None,
        workspace: str | Path | None = None,
    ) -> Agent:
        """
        Return a new agent with the provided attributes replaced.

        Args:
            model: Optional replacement model.
            contexts: Optional replacement global contexts.
            tools: Optional replacement default tools.
            system_prompt: Optional replacement system prompt template.
            workspace: Optional replacement workspace path.

        Returns:
            New immutable agent value with the requested overrides.
        """
        return dataclasses.replace(
            self,
            model=self.model if model is None else model,
            contexts=self.contexts if contexts is None else contexts,
            tools=self.tools if tools is None else tools,
            system_prompt=(
                self.system_prompt if system_prompt is None else system_prompt
            ),
            workspace=self.workspace if workspace is None else workspace,
        )

    def run(self, request: Request) -> Session:
        """
        Execute a request and return a pyflow session.

        Args:
            request: Request to execute.

        Returns:
            Pyflow session wrapper for this execution.
        """
        return self._run_request(
            request,
            runtime_model=self.model,
            interactive=True,
        )

    async def run_async(self, request: Request) -> Session:
        """
        Execute a request asynchronously and return a pyflow session.

        The async entry point runs through an isolated, non-interactive runtime
        so multiple awaited calls can execute concurrently without sharing one
        live model instance or driving display hooks from a worker thread.

        Args:
            request: Request to execute.

        Returns:
            Pyflow session wrapper for this execution.
        """
        return await asyncio.to_thread(self._run_async_request, request)

    def parallel[T](
        self,
        items: Sequence[T],
        build_request: Callable[[T], RequestInput],
        *,
        max_concurrency: int | None = None,
        max_requests_per_second: float | None = None,
    ) -> list[Session | ParallelFailure[T]]:
        """
        Execute many independent requests concurrently against this agent.

        Args:
            items: Input items to process.
            build_request: Callable that maps one item into a request-like input.
            max_concurrency: Optional maximum number of concurrent workers.
            max_requests_per_second: Optional global request start rate cap
                across workers. When ``None``, no explicit rate cap is applied.

        Returns:
            Ordered results containing either successful sessions or inline failures.
        """
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        if max_requests_per_second is not None and max_requests_per_second <= 0:
            raise ValueError("max_requests_per_second must be greater than 0.")
        if not items:
            return []

        results: list[Session | ParallelFailure[T] | None] = [None] * len(items)
        requests: list[tuple[int, T, Request]] = []

        for index, item in enumerate(items):
            try:
                request = convert_to_request(build_request(item))
            except Exception as exc:
                results[index] = ParallelFailure(
                    index=index,
                    item=item,
                    phase="build_request",
                    error=exc,
                    session=None,
                )
                continue
            requests.append((index, item, request))

        if not requests:
            return cast(list[Session | ParallelFailure[T]], results)

        worker_count = len(requests)
        if max_concurrency is not None:
            worker_count = min(worker_count, max_concurrency)
        request_pacer: _ParallelRequestPacer | None = None
        if max_requests_per_second is not None:
            request_pacer = _ParallelRequestPacer(
                max_requests_per_second=max_requests_per_second
            )

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="pyflow-parallel",
        ) as executor:
            future_to_index: dict[Future[Session | ParallelFailure[T]], int] = {}
            for index, item, request in requests:
                future = executor.submit(
                    self._run_parallel_worker,
                    index,
                    item,
                    request,
                    request_pacer,
                )
                future_to_index[future] = index

            for future in as_completed(future_to_index):
                index = future_to_index[future]
                results[index] = future.result()

        return cast(list[Session | ParallelFailure[T]], results)

    def __rrshift__(self, lhs: RequestInput) -> Session:
        """
        Execute request-like input via ``>>``.

        Args:
            lhs: Request-like input (``Request`` or single-step input).

        Returns:
            Pyflow session wrapper for this execution.
        """
        return self.run(convert_to_request(lhs))

    def append_message(
        self,
        conversation: BaseConversation,
        request: Request,
        *,
        include_global_context: bool = False,
    ) -> None:
        """Append a request message to an existing conversation."""
        message = request.render()
        if include_global_context:
            message = self._render_message(request)
        conversation.send_message(message)

    def _render_message(self, request: Request) -> str:
        """
        Render a request with optional agent-level context preamble.

        Args:
            request: Request to render.

        Returns:
            Full prompt string sent to OpenHands.
        """
        rendered_request = request.render()
        if not self.contexts:
            return rendered_request

        lines = ["Context:"]
        for context in self.contexts:
            lines.append(f"- {context.render()}")
        lines.append("")
        lines.append(rendered_request)
        return "\n".join(lines)

    def _create_conversation(
        self,
        *,
        runtime_model: Model,
        interactive: bool,
    ) -> BaseConversation:
        apply_default_backend_log_policy()
        if interactive:
            visualizer = conversation_visualizer_for_environment()
            if visualizer is not None:
                return Conversation(
                    agent=self._build_openhands_agent(
                        runtime_model=runtime_model,
                        interactive=interactive,
                    ),
                    workspace=self.workspace,
                    visualizer=visualizer,
                )
            return Conversation(
                agent=self._build_openhands_agent(
                    runtime_model=runtime_model,
                    interactive=interactive,
                ),
                workspace=self.workspace,
                visualizer=None,
            )
        return Conversation(
            agent=self._build_openhands_agent(
                runtime_model=runtime_model,
                interactive=interactive,
            ),
            workspace=self.workspace,
            visualizer=None,
        )

    def _prepare_session(
        self,
        request: Request,
        *,
        runtime_model: Model,
        interactive: bool,
    ) -> Session:
        conversation = self._create_conversation(
            runtime_model=runtime_model,
            interactive=interactive,
        )
        self.append_message(conversation, request, include_global_context=True)
        return Session(
            agent=self,
            conversation=conversation,
            output_spec=request.output_spec,
        )

    def _run_prepared_session(
        self,
        session: Session,
        *,
        interactive: bool,
    ) -> Session:
        if interactive:
            prepare_live_render(session.conversation, start_event_index=0)
        session.conversation.run()
        if interactive:
            sync_interactive_session(session, start_event_index=0)
        return session

    def _run_request(
        self,
        request: Request,
        *,
        runtime_model: Model,
        interactive: bool,
    ) -> Session:
        session = self._prepare_session(
            request,
            runtime_model=runtime_model,
            interactive=interactive,
        )
        return self._run_prepared_session(session, interactive=interactive)

    def _run_async_request(self, request: Request) -> Session:
        return self._run_request(
            request,
            runtime_model=self.model._fresh_runtime_model(),
            interactive=False,
        )

    def _run_parallel_worker[T](
        self,
        index: int,
        item: T,
        request: Request,
        request_pacer: _ParallelRequestPacer | None,
    ) -> Session | ParallelFailure[T]:
        session: Session | None = None
        try:
            runtime_model = self.model._fresh_runtime_model()
            session = self._prepare_session(
                request,
                runtime_model=runtime_model,
                interactive=False,
            )
            if request_pacer is not None:
                request_pacer.wait_turn()
            return self._run_prepared_session(session, interactive=False)
        except Exception as exc:
            return ParallelFailure(
                index=index,
                item=item,
                phase="run",
                error=exc,
                session=session,
            )

    def _build_openhands_agent(
        self,
        *,
        runtime_model: Model,
        interactive: bool,
    ) -> OpenHandsAgent:
        tool_specs = compile_openhands_tools(self.tools)
        self._validate_tool_calling_support(
            runtime_model=runtime_model,
            tool_specs=tool_specs,
        )
        return OpenHandsAgent(
            llm=runtime_model.inner_llm,
            tools=list(tool_specs),
            system_prompt_filename=str(self.system_prompt),
            system_prompt_kwargs={"cli_mode": interactive},
        )

    def _validate_tool_calling_support(
        self,
        *,
        runtime_model: Model,
        tool_specs: Sequence[OpenHandsToolSpec],
    ) -> None:
        if not tool_specs:
            return

        llm = runtime_model.inner_llm
        if llm.uses_responses_api() or not llm.native_tool_calling:
            return

        model_info = llm.model_info
        if model_info is None:
            return

        supports_function_calling = model_info.get("supports_function_calling")
        if supports_function_calling is not False:
            return

        model_name = llm.model_canonical_name or llm.model
        raise ValueError(
            f"Model '{model_name}' is configured with native tool calling, "
            "but LiteLLM reports that it does not support function/tool calls. "
            "Choose a model with native tool support or set "
            "`native_tool_calling=False` so OpenHands can mock tool calls."
        )


class _ParallelRequestPacer:
    def __init__(self, *, max_requests_per_second: float) -> None:
        self._interval_seconds = 1.0 / max_requests_per_second
        self._next_allowed_at = 0.0
        self._lock = Lock()

    def wait_turn(self) -> None:
        while True:
            with self._lock:
                now = monotonic()
                if now >= self._next_allowed_at:
                    self._next_allowed_at = now + self._interval_seconds
                    return
                sleep_duration = self._next_allowed_at - now
            sleep(sleep_duration)
