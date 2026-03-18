from __future__ import annotations

from abc import abstractmethod
import importlib
import inspect
import json
import logging
from dataclasses import dataclass, field
from itertools import count
from types import NoneType
from typing import (
    Annotated,
    Any,
    Callable,
    Iterable,
    ParamSpec,
    Sequence,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

from openhands.sdk.conversation.base import BaseConversation
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


Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")

logger = logging.getLogger(__name__)
_REGISTERED_TOOLS: dict[str, "FunctionTool[..., Any]"] = {}
_GENERATED_TOOL_TYPE_IDS = count()


class Tool(Context):
    """Common pyflow abstraction for attachable tools."""

    @abstractmethod
    def tool_name(self) -> str:
        """Return the OpenHands-visible tool name."""

    @abstractmethod
    def to_openhands_spec(self) -> OpenHandsToolSpec:
        """Build the OpenHands tool spec for runtime compilation."""

    def render(self) -> str:
        names = _ordered_unique(
            flattened_tool.tool_name()
            for flattened_tool in flatten_tools((self,))
        )
        noun = "tool" if len(names) == 1 else "tools"
        return f"Use {noun}: {', '.join(names)}."


@dataclass(frozen=True, kw_only=True)
class ToolContext:
    """Runtime context injected into pyflow tool functions."""

    conversation: BaseConversation | None = None


@dataclass(frozen=True)
class FunctionTool[**Parameters, Result](Tool):
    """
    Pyflow wrapper for either a local Python tool or an imported OpenHands tool.

    Field meaning:
    - ``name``: stable runtime tool name exposed to OpenHands and the DSL.
    - ``description``: human-readable tool description, usually from the function docstring.
    - ``function``: original Python callable for pyflow-backed tools. ``None`` for wrapped
      OpenHands tools because pyflow cannot execute them directly.
    - ``annotations``: OpenHands-compatible behavior hints for pyflow-backed tools.
    - ``_action_type``: generated or reused OpenHands ``Action`` model describing tool input.
      Present only for pyflow-backed tools and exposed via ``action_type``.
    - ``_observation_type``: generated or reused OpenHands ``Observation`` model describing
      tool output. Present only for pyflow-backed tools and exposed via
      ``observation_type``.

    Mode summary:
    - Local pyflow tool: all fields above are populated, and the wrapper is callable.
    - Wrapped OpenHands tool: only ``name`` and ``description`` are stored here; execution
      stays inside the OpenHands registry.
    """

    name: str
    description: str
    function: Callable[Parameters, Result] | None = field(default=None, repr=False, compare=False)
    annotations: ToolAnnotations | None = field(default=None, repr=False, compare=False)
    _action_type: type[Action] | None = field(default=None, repr=False, compare=False)
    _observation_type: type[Observation] | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_function(
        cls: type[FunctionTool[Parameters, Result]],
        function: Callable[Parameters, Result],
        *,
        name: str | None = None,
        read_only: bool = False,
        destructive: bool = True,
        idempotent: bool = False,
        open_world: bool = True,
    ) -> FunctionTool[Parameters, Result]:
        """Register a Python function as a pyflow tool."""
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
        parameters, return_annotation, accepts_context = _inspect_tool_signature(
            resolved_name,
            function,
            signature,
        )
        _warn_about_tool_replacement(
            resolved_name,
            source="function-backed tool",
        )
        generated_type_name_prefix = _next_generated_type_name_prefix(resolved_name)

        action_type, parameter_names = _build_action_type(
            generated_type_name_prefix,
            parameters,
        )
        observation_type, returns_observation = _build_observation_type(
            generated_type_name_prefix,
            return_annotation,
        )
        tool_instance = cast(
            FunctionTool[Parameters, Result],
            cls(
                name=resolved_name,
                description=description,
                function=function,
                annotations=_build_tool_annotations(
                    resolved_name,
                    read_only=read_only,
                    destructive=destructive,
                    idempotent=idempotent,
                    open_world=open_world,
                ),
                _action_type=action_type,
                _observation_type=observation_type,
            ),
        )
        definition = tool_instance._build_openhands_definition(
            generated_type_name_prefix=generated_type_name_prefix,
            parameter_names=parameter_names,
            returns_observation=returns_observation,
            accepts_context=accepts_context,
        )
        register_tool(resolved_name, definition)
        _REGISTERED_TOOLS[resolved_name] = tool_instance
        return tool_instance

    @classmethod
    def from_openhands(
        cls,
        *,
        name: str,
        module_name: str,
        description: str | None = None,
    ) -> FunctionTool[..., Any]:
        """Import and wrap an OpenHands tool that registers itself by module import."""
        if not name.strip():
            raise ValueError("OpenHands tool wrappers must have a non-empty name.")
        if not module_name.strip():
            raise ValueError("OpenHands tool wrappers must have a non-empty module name.")

        importlib.import_module(module_name)
        if name not in list_registered_tools():
            raise ValueError(f"OpenHands tool '{name}' is not registered.")

        tool_instance = cls(
            name=name,
            description=description or f"OpenHands tool '{name}'.",
        )
        _REGISTERED_TOOLS[name] = tool_instance
        return tool_instance

    def __call__(self, *args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
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

    def to_openhands_spec(self) -> OpenHandsToolSpec:
        return OpenHandsToolSpec(name=self.name)

    def _build_openhands_definition(
        self,
        *,
        generated_type_name_prefix: str,
        parameter_names: Sequence[str],
        returns_observation: bool,
        accepts_context: bool,
    ) -> OpenHandsToolDefinition:
        if self.function is None:
            raise TypeError(
                f"Tool '{self.name}' is OpenHands-backed and does not define a local executor."
            )

        executor = _FunctionToolExecutor(
            function=self.function,
            observation_type=self.observation_type,
            parameter_names=parameter_names,
            returns_observation=returns_observation,
            accepts_context=accepts_context,
        )

        def _unsupported_create(cls, conv_state=None, **params):  # noqa: ANN001, ANN202, ARG001
            if params:
                raise ValueError(f"Tool '{self.name}' does not accept OpenHands tool params.")
            raise NotImplementedError("Pyflow function tools are registered as fixed instances.")

        definition_type = cast(
            type[OpenHandsToolDefinition],
            type(
                f"{generated_type_name_prefix}ToolDefinition",
                (OpenHandsToolDefinition,),
                {
                    "__module__": __name__,
                    "name": self.name,
                    "create": classmethod(_unsupported_create),
                },
            ),
        )
        return definition_type(
            description=self.description,
            action_type=self.action_type,
            observation_type=self.observation_type,
            annotations=self.annotations,
            executor=executor,
        )


@dataclass(frozen=True)
class ToolSet(Tool):
    tools: Sequence[Tool]

    def __post_init__(self) -> None:
        if not self.tools:
            raise ValueError("ToolSet must contain at least one tool.")

        for tool in self.tools:
            if not isinstance(tool, Tool):
                raise TypeError("ToolSet only accepts Tool instances.")

        object.__setattr__(self, "tools", tuple(self.tools))

    def tool_name(self) -> str:
        raise TypeError("ToolSet does not have a single tool name.")

    def to_openhands_spec(self) -> OpenHandsToolSpec:
        raise TypeError("ToolSet must be flattened before OpenHands compilation.")


class _FunctionToolExecutor(ToolExecutor[Action, Observation]):
    def __init__(
        self,
        function: Callable[..., Any],
        observation_type: type[Observation],
        parameter_names: Sequence[str],
        returns_observation: bool,
        accepts_context: bool,
    ) -> None:
        self._function = function
        self._observation_type = observation_type
        self._parameter_names = tuple(parameter_names)
        self._returns_observation = returns_observation
        self._accepts_context = accepts_context

    def __call__(
        self,
        action: Action,
        conversation: BaseConversation | None = None,
    ) -> Observation:
        arguments = {
            parameter_name: getattr(action, parameter_name)
            for parameter_name in self._parameter_names
        }
        if self._accepts_context:
            result = self._function(
                ToolContext(conversation=conversation),
                **arguments,
            )
        else:
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


@overload
def tool(
    value: Callable[Parameters, Result],
    /,
    *,
    name: str | None = None,
    read_only: bool = False,
    destructive: bool = True,
    idempotent: bool = False,
    open_world: bool = True,
) -> FunctionTool[Parameters, Result]: ...


@overload
def tool(
    value: None = None,
    /,
    *,
    name: str | None = None,
    read_only: bool = False,
    destructive: bool = True,
    idempotent: bool = False,
    open_world: bool = True,
) -> Callable[[Callable[Parameters, Result]], FunctionTool[Parameters, Result]]: ...


def tool(
    value: Callable[..., Any] | None = None,
    /,
    *,
    name: str | None = None,
    read_only: bool = False,
    destructive: bool = True,
    idempotent: bool = False,
    open_world: bool = True,
) -> FunctionTool[..., Any] | Callable[[Callable[..., Any]], FunctionTool[..., Any]]:
    """
    Register function-backed tools via the public DSL.

    Supported forms:
    - ``@tool`` registers a function-backed tool using the function name.
    - ``@tool(read_only=True, ...)`` registers a function-backed tool with annotations.
    - ``@tool(name="custom_name")`` registers a function-backed tool with an explicit name.
    - ``tool(existing_function, ...)`` registers an already-defined callable.
    """
    if callable(value):
        return FunctionTool.from_function(
            value,
            name=name,
            read_only=read_only,
            destructive=destructive,
            idempotent=idempotent,
            open_world=open_world,
        )

    if value is None:

        def decorator(function: Callable[..., Any]) -> FunctionTool[..., Any]:
            return FunctionTool.from_function(
                function,
                name=name,
                read_only=read_only,
                destructive=destructive,
                idempotent=idempotent,
                open_world=open_world,
            )

        return decorator

    raise TypeError(
        "Use @tool or @tool(...) to define a tool. Use tools(...) to resolve registered tools."
    )


def tools(*values: Tool | str) -> Tool:
    """Resolve registered tools by name and group multiple tools when needed."""
    if not values:
        raise TypeError("tools(...) requires at least one tool name or Tool instance.")

    resolved = tuple(_convert_tool(value) for value in values)
    if len(resolved) == 1:
        return resolved[0]
    return ToolSet(tools=resolved)

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


def compile_openhands_tools(*tool_groups: Sequence[Tool]) -> Sequence[OpenHandsToolSpec]:
    flattened: list[Tool] = []
    for group in tool_groups:
        flattened.extend(flatten_tools(group))

    merged: dict[str, Tool] = {}
    for resolved_tool in flattened:
        name = resolved_tool.tool_name()
        if name in merged:
            merged.pop(name)
        merged[name] = resolved_tool

    return tuple(tool.to_openhands_spec() for tool in merged.values())


def _build_action_type(
    generated_type_name_prefix: str,
    parameters: Sequence[inspect.Parameter],
) -> tuple[type[Action], Sequence[str]]:
    fields: dict[str, tuple[Any, Any]] = {}
    parameter_names: list[str] = []

    for parameter in parameters:
        fields[parameter.name] = (parameter.annotation, parameter.default)
        parameter_names.append(parameter.name)

    action_type = cast(
        type[Action],
        cast(Any, create_model)(
            f"{generated_type_name_prefix}Action",
            __base__=Action,
            __module__=__name__,
            **fields,
        ),
    )
    return action_type, tuple(parameter_names)


def _build_observation_type(
    generated_type_name_prefix: str,
    return_annotation: Any,
) -> tuple[type[Observation], bool]:
    if isinstance(return_annotation, type) and issubclass(return_annotation, Observation):
        return return_annotation, True

    default = None if return_annotation is NoneType else ...
    observation_type = cast(
        type[Observation],
        cast(Any, create_model)(
            f"{generated_type_name_prefix}Observation",
            __base__=Observation,
            __module__=__name__,
            result=(return_annotation, default),
        ),
    )
    return observation_type, False


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


def _next_generated_type_name_prefix(tool_name: str) -> str:
    return f"{_pascal_case(tool_name)}{next(_GENERATED_TOOL_TYPE_IDS)}"


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


def _inspect_tool_signature(
    tool_name: str,
    function: Callable[..., Any],
    signature: inspect.Signature,
) -> tuple[Sequence[inspect.Parameter], Any, bool]:
    annotations = inspect.get_annotations(function, eval_str=True)
    parameters: list[inspect.Parameter] = []
    accepts_context = False

    for index, parameter in enumerate(signature.parameters.values()):
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise ValueError(
                f"Tool function '{tool_name}' has unsupported parameter kind '{parameter.kind.description}'."
            )

        annotation = annotations.get(parameter.name, parameter.annotation)
        if _is_tool_context_annotation(annotation):
            if index != 0:
                raise ValueError(
                    f"Tool function '{tool_name}' may only declare ToolContext as its first parameter."
                )
            accepts_context = True
            continue
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
            parameter.replace(
                annotation=annotation,
                default=default,
            )
        )

    return_annotation = annotations.get("return", signature.return_annotation)
    if return_annotation is inspect.Signature.empty:
        raise ValueError(f"Tool function '{tool_name}' must declare a return type.")
    if return_annotation is None:
        return_annotation = NoneType

    return tuple(parameters), return_annotation, accepts_context


def _convert_tool(value: Tool | str) -> Tool:
    """Convert a tool object or registered tool name into a ``Tool`` instance."""
    if isinstance(value, Tool):
        return value
    if isinstance(value, str):
        return _resolve_registered_tool(value)
    raise TypeError(f"Unsupported tool input: {type(value)!r}")


def _resolve_registered_tool(name: str) -> FunctionTool[..., Any]:
    tool_instance = _REGISTERED_TOOLS.get(name)
    if tool_instance is not None:
        return tool_instance

    available = sorted(_REGISTERED_TOOLS.keys())
    raise ValueError(
        f"Unknown tool '{name}'. Define it with @tool or register it via "
        f"FunctionTool.from_openhands(...), then resolve it with tools(...). "
        f"Available tools: {available}"
    )


def _warn_about_tool_replacement(name: str, *, source: str) -> None:
    if name in _REGISTERED_TOOLS or name in list_registered_tools():
        logger.warning("Replacing tool '%s' with %s.", name, source)


def _build_tool_annotations(
    name: str,
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> ToolAnnotations:
    return ToolAnnotations(
        title=name,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


def _is_tool_context_annotation(annotation: Any) -> bool:
    if annotation is ToolContext:
        return True

    if get_origin(annotation) is Annotated:
        annotated_type, *_ = get_args(annotation)
        return annotated_type is ToolContext

    return isinstance(annotation, type) and issubclass(annotation, ToolContext)
