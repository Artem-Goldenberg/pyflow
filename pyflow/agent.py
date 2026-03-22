from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, cast, Sequence

from openhands.sdk import Agent as OpenHandsAgent
from openhands.sdk import Conversation
from openhands.sdk.conversation.base import BaseConversation

from pyflow.context import Context
from pyflow.display import (
    conversation_visualizer_for_environment,
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


@dataclass(frozen=True, kw_only=True)
class Agent:
    """
    Pyflow runtime sink backed by a fresh OpenHands agent per run.

    Attributes:
        model: Pyflow model that owns the OpenHands LLM used for execution.
        contexts: Contexts rendered globally before request steps.
        tools: Tools attached to every run.
        workspace: OpenHands workspace path for execution.
    """

    model: Model
    contexts: Sequence[Context] = ()
    tools: Sequence[Tool] = field(default_factory=default_agent_tools)
    workspace: str | Path = field(default_factory=Path.cwd)

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

    def parallel[T](
        self,
        items: Sequence[T],
        build_request: Callable[[T], RequestInput],
        *,
        max_concurrency: int | None = None,
    ) -> list[Session | ParallelFailure[T]]:
        """
        Execute many independent requests concurrently against this agent.

        Args:
            items: Input items to process.
            build_request: Callable that maps one item into a request-like input.
            max_concurrency: Optional maximum number of concurrent workers.

        Returns:
            Ordered results containing either successful sessions or inline failures.
        """
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
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
                    agent=self._build_openhands_agent(runtime_model=runtime_model),
                    workspace=self.workspace,
                    visualizer=visualizer,
                )
            return Conversation(
                agent=self._build_openhands_agent(runtime_model=runtime_model),
                workspace=self.workspace,
                visualizer=None,
            )
        return Conversation(
            agent=self._build_openhands_agent(runtime_model=runtime_model),
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
        return Session(agent=self, conversation=conversation)

    def _run_prepared_session(
        self,
        session: Session,
        *,
        interactive: bool,
    ) -> Session:
        session.conversation.run()
        if interactive:
            sync_interactive_session(session)
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

    def _run_parallel_worker[T](
        self,
        index: int,
        item: T,
        request: Request,
    ) -> Session | ParallelFailure[T]:
        session: Session | None = None
        try:
            runtime_model = self.model._fresh_runtime_model()
            session = self._prepare_session(
                request,
                runtime_model=runtime_model,
                interactive=False,
            )
            return self._run_prepared_session(session, interactive=False)
        except Exception as exc:
            return ParallelFailure(
                index=index,
                item=item,
                phase="run",
                error=exc,
                session=session,
            )

    def _build_openhands_agent(self, *, runtime_model: Model) -> OpenHandsAgent:
        tool_specs = compile_openhands_tools(self.tools)
        return OpenHandsAgent(
            llm=runtime_model.inner_llm,
            tools=list(tool_specs),
            system_prompt_kwargs={"cli_mode": True},
        )
