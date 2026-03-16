from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass, field
from types import NoneType
from typing import Any, Callable, Iterable, ParamSpec, Sequence, TypeVar, cast, get_type_hints, overload

from openhands.sdk.llm import TextContent
from openhands.sdk.tool import (
    Action,
    Observation,
    Tool as OpenHandsToolSpec,
    ToolAnnotations,
    ToolDefinition as OpenHandsToolDefinition,
    ToolExecutor,
    list_registered_tools,
    register_tool,
)
from pydantic import create_model

from pyflow.context import Context


P = ParamSpec("P")
R = TypeVar("R")

_RESERVED_OPENHANDS_TOOL_NAMES: frozenset[str] = frozenset(
    {"terminal", "read_file", "apply_patch"}
)
_PYFLOW_TOOLS: dict[str, "FunctionTool[..., Any]"] = {}


class Tool(Context):
    """Common pyflow abstraction for attachable tools."""

    def tool_name(self) -> str:
        raise NotImplementedError

    def identity(self) -> tuple[str, str]:
        raise NotImplementedError

    def to_openhands_spec(self) -> OpenHandsToolSpec:
        raise NotImplementedError

    def render(self) -> str:
        names = _ordered_unique(
            flattened_tool.tool_name()
            for flattened_tool in flatten_tools((self,))
        )
        noun = "tool" if len(names) == 1 else "tools"
        return f"Use {noun}: {', '.join(names)}."


@dataclass(frozen=True)
class FunctionTool[**ToolP, ToolR](Tool):
    name: str
    description: str
    function: Callable[ToolP, ToolR] | None = field(default=None, repr=False, compare=False)
    _action_type: type[Action] | None = field(default=None, repr=False, compare=False)
    _observation_type: type[Observation] | None = field(default=None, repr=False, compare=False)
    _definition: OpenHandsToolDefinition | None = field(default=None, repr=False, compare=False)
    _fingerprint: str | None = field(default=None, repr=False, compare=False)
    _parameter_names: Sequence[str] = field(default=(), repr=False, compare=False)
    _openhands_module_name: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_function(
        cls: type[FunctionTool[P, R]],
        function: Callable[P, R],
        *,
        name: str | None = None,
    ) -> FunctionTool[P, R]:
        if inspect.iscoroutinefunction(function):
            raise ValueError("Async tool functions are not supported.")

        resolved_name = name or getattr(function, "__name__", "")
        if not resolved_name.strip():
            raise ValueError("Tool functions must have a non-empty name.")

        description = inspect.getdoc(function)
        if not description:
            raise ValueError(
                f"Tool function '{resolved_name}' must define a docstring description."
            )

        signature = inspect.signature(function)
        parameters, return_annotation = _inspect_tool_signature(
            resolved_name,
            function,
            signature,
        )
        _guard_reserved_openhands_tool_name(resolved_name)
        fingerprint = _tool_fingerprint(
            name=resolved_name,
            description=description,
            parameters=parameters,
            return_annotation=return_annotation,
        )
        parameter_names = tuple(parameter.name for parameter in parameters)
        existing_tool = _PYFLOW_TOOLS.get(resolved_name)
        if existing_tool is not None:
            if existing_tool._fingerprint != fingerprint:
                raise ValueError(
                    f"Tool '{resolved_name}' is already registered with a different definition."
                )
            return cast(FunctionTool[P, R], existing_tool)

        if resolved_name in list_registered_tools():
            raise ValueError(
                f"Tool '{resolved_name}' is already registered in OpenHands."
            )

        action_type, parameter_names = _build_action_type(resolved_name, parameters)
        observation_type, returns_observation = _build_observation_type(
            resolved_name,
            return_annotation,
        )
        definition = _build_function_tool_definition(
            name=resolved_name,
            description=description,
            function=function,
            action_type=action_type,
            observation_type=observation_type,
            parameter_names=parameter_names,
            returns_observation=returns_observation,
        )
        register_tool(resolved_name, definition)

        tool_instance = cast(
            FunctionTool[P, R],
            cls(
                name=resolved_name,
                description=description,
                function=function,
                _action_type=action_type,
                _observation_type=observation_type,
                _definition=definition,
                _fingerprint=fingerprint,
                _parameter_names=parameter_names,
            ),
        )
        _PYFLOW_TOOLS[resolved_name] = tool_instance
        return tool_instance

    @classmethod
    def from_openhands(
        cls,
        *,
        name: str,
        module_name: str,
        description: str | None = None,
    ) -> FunctionTool[..., Any]:
        if not name.strip():
            raise ValueError("OpenHands tool wrappers must have a non-empty name.")
        if not module_name.strip():
            raise ValueError("OpenHands tool wrappers must have a non-empty module name.")

        return cls(
            name=name,
            description=description or f"OpenHands tool '{name}'.",
            _openhands_module_name=module_name,
        )

    def __call__(self, *args: ToolP.args, **kwargs: ToolP.kwargs) -> ToolR:
        if self.function is None:
            raise TypeError(
                f"Tool '{self.name}' is OpenHands-backed and cannot be called directly."
            )
        return self.function(*args, **kwargs)

    @property
    def action_type(self) -> type[Action]:
        if self._action_type is None:
            raise TypeError(
                f"Tool '{self.name}' is OpenHands-backed and does not expose an action type."
            )
        return self._action_type

    @property
    def observation_type(self) -> type[Observation]:
        if self._observation_type is None:
            raise TypeError(
                f"Tool '{self.name}' is OpenHands-backed and does not expose an observation type."
            )
        return self._observation_type

    def tool_name(self) -> str:
        return self.name

    def identity(self) -> tuple[str, str]:
        if self._fingerprint is not None:
            return ("pyflow", self._fingerprint)
        return ("openhands", self.name)

    def to_openhands_spec(self) -> OpenHandsToolSpec:
        if self._openhands_module_name is not None:
            importlib.import_module(self._openhands_module_name)
            if self.name not in list_registered_tools():
                raise ValueError(f"OpenHands tool '{self.name}' is not registered.")
        return OpenHandsToolSpec(name=self.name)


@dataclass(frozen=True)
class ToolSet(Tool):
    tools: Sequence[Tool]

    def __post_init__(self) -> None:
        if not self.tools:
            raise ValueError("ToolSet must contain at least one tool.")

        for tool in self.tools:
            if not isinstance(tool, Tool):
                raise TypeError("tool.use(...) only accepts Tool instances.")

        object.__setattr__(self, "tools", tuple(self.tools))


class _FunctionToolExecutor(ToolExecutor[Action, Observation]):
    def __init__(
        self,
        function: Callable[..., Any],
        observation_type: type[Observation],
        parameter_names: Sequence[str],
        returns_observation: bool,
    ) -> None:
        self._function = function
        self._observation_type = observation_type
        self._parameter_names = tuple(parameter_names)
        self._returns_observation = returns_observation

    def __call__(
        self,
        action: Action,
        conversation=None,  # noqa: ARG002 - OpenHands executor signature
    ) -> Observation:
        arguments = {
            parameter_name: getattr(action, parameter_name)
            for parameter_name in self._parameter_names
        }
        result = self._function(**arguments)

        if self._returns_observation:
            if isinstance(result, Observation):
                return result
            return self._observation_type.model_validate(result)

        return self._observation_type.model_validate(
            {
                "result": result,
                "content": [TextContent(text=_render_result(result))],
            }
        )


class _ToolFactory:
    @overload
    def __call__(self, value: str, /) -> FunctionTool[..., Any]: ...

    @overload
    def __call__(self, value: Callable[P, R], /) -> FunctionTool[P, R]: ...

    @overload
    def __call__(
        self,
        value: Callable[P, R],
        /,
        *,
        name: str,
    ) -> FunctionTool[P, R]: ...

    @overload
    def __call__(
        self,
        value: None = None,
        /,
        *,
        name: str,
    ) -> Callable[[Callable[P, R]], FunctionTool[P, R]]: ...

    def __call__(
        self,
        value: Callable[..., Any] | str | None = None,
        /,
        *,
        name: str | None = None,
    ) -> FunctionTool[..., Any] | Callable[[Callable[..., Any]], FunctionTool[..., Any]]:
        if callable(value):
            return FunctionTool.from_function(value, name=name)

        if isinstance(value, str):
            if name is not None:
                raise TypeError("tool('name') does not accept the 'name=' keyword.")
            return _resolve_function_tool(value)

        if value is None and name is not None:

            def decorator(function: Callable[..., Any]) -> FunctionTool[..., Any]:
                return FunctionTool.from_function(function, name=name)

            return decorator

        raise TypeError("Use @tool, @tool(name='...'), or tool('existing_name').")

    def use(self, *tools: Tool | str) -> ToolSet:
        return ToolSet(tools=tuple(_coerce_tool(tool) for tool in tools))


tool = _ToolFactory()


def collect_request_tools(request: Any) -> Sequence[Tool]:
    collected: list[Tool] = []
    for step in request.steps:
        for attachment in step.attachments:
            if isinstance(attachment, Tool):
                collected.append(attachment)
    return tuple(collected)


def compile_openhands_tools(*tool_groups: Sequence[Tool]) -> Sequence[OpenHandsToolSpec]:
    flattened: list[Tool] = []
    for group in tool_groups:
        flattened.extend(flatten_tools(group))

    merged: dict[str, Tool] = {}
    for resolved_tool in flattened:
        name = resolved_tool.tool_name()
        existing = merged.get(name)
        if existing is not None:
            if existing.identity() != resolved_tool.identity():
                raise ValueError(
                    f"Tool '{name}' was attached multiple times with incompatible definitions."
                )
            continue

        merged[name] = resolved_tool

    return tuple(tool.to_openhands_spec() for tool in merged.values())


def _build_action_type(
    tool_name: str,
    parameters: Sequence[_ToolParameter],
) -> tuple[type[Action], Sequence[str]]:
    fields: dict[str, tuple[Any, Any]] = {}
    parameter_names: list[str] = []

    for parameter in parameters:
        fields[parameter.name] = (parameter.annotation, parameter.default)
        parameter_names.append(parameter.name)

    action_type = cast(
        type[Action],
        cast(Any, create_model)(
            f"{_pascal_case(tool_name)}Action",
            __base__=Action,
            __module__=__name__,
            **fields,
        ),
    )
    return action_type, tuple(parameter_names)


def _build_observation_type(
    tool_name: str,
    return_annotation: Any,
) -> tuple[type[Observation], bool]:
    if isinstance(return_annotation, type) and issubclass(return_annotation, Observation):
        return return_annotation, True

    default = None if return_annotation is NoneType else ...
    observation_type = cast(
        type[Observation],
        cast(Any, create_model)(
            f"{_pascal_case(tool_name)}Observation",
            __base__=Observation,
            __module__=__name__,
            result=(return_annotation, default),
        ),
    )
    return observation_type, False


def _build_function_tool_definition(
    *,
    name: str,
    description: str,
    function: Callable[..., Any],
    action_type: type[Action],
    observation_type: type[Observation],
    parameter_names: Sequence[str],
    returns_observation: bool,
) -> OpenHandsToolDefinition:
    executor = _FunctionToolExecutor(
        function=function,
        observation_type=observation_type,
        parameter_names=parameter_names,
        returns_observation=returns_observation,
    )

    def _unsupported_create(cls, conv_state=None, **params):  # noqa: ANN001, ANN202, ARG001
        if params:
            raise ValueError(f"Tool '{name}' does not accept OpenHands tool params.")
        raise NotImplementedError("Pyflow function tools are registered as fixed instances.")

    definition_type = cast(
        type[OpenHandsToolDefinition],
        type(
            f"{_pascal_case(name)}ToolDefinition",
            (OpenHandsToolDefinition,),
            {
                "__module__": __name__,
                "name": name,
                "create": classmethod(_unsupported_create),
            },
        ),
    )
    return definition_type(
        description=description,
        action_type=action_type,
        observation_type=observation_type,
        annotations=ToolAnnotations(
            title=name,
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
        executor=executor,
    )


def _render_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if result is None:
        return "null"
    if isinstance(result, (bool, int, float)):
        return json.dumps(result)
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), sort_keys=True, default=str)
    if isinstance(result, (dict, list, tuple)):
        return json.dumps(result, sort_keys=True, default=str)
    return str(result)


def _tool_fingerprint(
    *,
    name: str,
    description: str,
    parameters: Sequence[_ToolParameter],
    return_annotation: Any,
) -> str:
    return json.dumps(
        {
            "name": name,
            "description": description,
            "parameters": [
                {
                    "name": parameter.name,
                    "annotation": _stable_repr(parameter.annotation),
                    "default": _stable_repr(parameter.default),
                }
                for parameter in parameters
            ],
            "return_annotation": _stable_repr(return_annotation),
        },
        sort_keys=True,
        default=str,
    )


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        ordered.append(value)
        seen.add(value)
    return ordered


def _pascal_case(value: str) -> str:
    parts = [part for part in value.replace("-", "_").split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Tool"


def flatten_tools(tools: Sequence[Tool]) -> Sequence[Tool]:
    flattened: list[Tool] = []
    for tool in tools:
        if isinstance(tool, ToolSet):
            flattened.extend(flatten_tools(tool.tools))
            continue
        if isinstance(tool, Tool):
            flattened.append(tool)
            continue
        raise TypeError(f"Unsupported tool input: {type(tool)!r}")
    return tuple(flattened)


def default_agent_tools() -> Sequence[Tool]:
    return (terminal_tool, read_file_tool, apply_patch_tool)


@dataclass(frozen=True)
class _ToolParameter:
    name: str
    annotation: Any
    default: Any


def _inspect_tool_signature(
    tool_name: str,
    function: Callable[..., Any],
    signature: inspect.Signature,
) -> tuple[Sequence[_ToolParameter], Any]:
    hints = get_type_hints(function)
    parameters: list[_ToolParameter] = []

    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise ValueError(
                f"Tool function '{tool_name}' has unsupported parameter kind '{parameter.kind.description}'."
            )

        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Signature.empty:
            raise ValueError(
                f"Tool function '{tool_name}' parameter '{parameter.name}' must be annotated."
            )

        default = (
            ...
            if parameter.default is inspect.Signature.empty
            else parameter.default
        )
        parameters.append(
            _ToolParameter(
                name=parameter.name,
                annotation=annotation,
                default=default,
            )
        )

    return_annotation = hints.get("return", signature.return_annotation)
    if return_annotation is inspect.Signature.empty:
        raise ValueError(f"Tool function '{tool_name}' must declare a return type.")

    return tuple(parameters), return_annotation


def _stable_repr(value: Any) -> str:
    if value is ...:
        return "required"
    if value is NoneType:
        return "NoneType"
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    return repr(value)


def _coerce_tool(value: Tool | str) -> Tool:
    if isinstance(value, Tool):
        return value
    if isinstance(value, str):
        return _resolve_function_tool(value)
    raise TypeError(f"Unsupported tool input: {type(value)!r}")


def _resolve_function_tool(name: str) -> FunctionTool[..., Any]:
    tool_instance = _PYFLOW_TOOLS.get(name)
    if tool_instance is not None:
        return tool_instance

    available = sorted(_PYFLOW_TOOLS.keys())
    raise ValueError(
        f"Unknown pyflow tool '{name}'. Define it with @tool first. "
        f"Available pyflow tools: {available}"
    )


def _guard_reserved_openhands_tool_name(name: str) -> None:
    if name in _RESERVED_OPENHANDS_TOOL_NAMES:
        raise ValueError(f"Tool '{name}' is already registered in OpenHands.")


terminal_tool = FunctionTool.from_openhands(
    name="terminal",
    module_name="openhands.tools.terminal",
)
read_file_tool = FunctionTool.from_openhands(
    name="read_file",
    module_name="openhands.tools.gemini.read_file",
)
apply_patch_tool = FunctionTool.from_openhands(
    name="apply_patch",
    module_name="openhands.tools.apply_patch",
)
