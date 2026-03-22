from __future__ import annotations

import argparse
import json
import keyword
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from urllib import request

from pydantic import SecretStr


DEFAULT_GENERATED_MODELS_PATH = Path("pyflow/generated_models.py")
DEFAULT_API_KEY_ENV_VAR = "API_KEY"

_SUPPORT_BLOCK_START = "# >>> PYFLOW_MODELS_SUPPORT_START"
_SUPPORT_BLOCK_END = "# <<< PYFLOW_MODELS_SUPPORT_END"
_PROVIDER_BLOCK_START_PREFIX = "# >>> PYFLOW_PROVIDER_MODELS_START: "
_PROVIDER_BLOCK_END_PREFIX = "# <<< PYFLOW_PROVIDER_MODELS_END: "


@dataclass(frozen=True, kw_only=True)
class _ModelEntry:
    model_id: str
    flat_alias: str
    nested_path: Sequence[str]


@dataclass(kw_only=True)
class _NamespaceNode:
    model: _ModelEntry | None = None
    children: dict[str, _NamespaceNode] = field(default_factory=dict)


def generate_models_from_provider(
    *,
    provider_name: str,
    base_url: str,
    output_path: str | Path = DEFAULT_GENERATED_MODELS_PATH,
    api_key: str | SecretStr | None = None,
    api_key_env_var: str = DEFAULT_API_KEY_ENV_VAR,
    models_path: str = "/models",
    timeout_seconds: float = 30.0,
) -> Path:
    """
    Discover provider models and upsert them into a generated module.

    Args:
        provider_name: Short provider alias used under ``Models.<provider_name>``.
        base_url: Provider base URL used for both discovery and runtime model construction.
        output_path: Importable module path that stores generated model bindings.
        api_key: Optional API key used for discovery.
        api_key_env_var: Environment variable fallback for discovery and runtime.
        models_path: Relative endpoint to discover models from (default ``/models``).
        timeout_seconds: HTTP timeout for discovery request.

    Returns:
        Path to the generated module file.
    """
    model_ids = discover_provider_models(
        base_url=base_url,
        api_key=api_key,
        api_key_env_var=api_key_env_var,
        models_path=models_path,
        timeout_seconds=timeout_seconds,
    )
    return generate_models_file(
        provider_name=provider_name,
        base_url=base_url,
        model_ids=model_ids,
        output_path=output_path,
        api_key_env_var=api_key_env_var,
    )


def discover_provider_models(
    *,
    base_url: str,
    api_key: str | SecretStr | None = None,
    api_key_env_var: str = DEFAULT_API_KEY_ENV_VAR,
    models_path: str = "/models",
    timeout_seconds: float = 30.0,
) -> Sequence[str]:
    """
    Discover available model IDs from a provider ``/models`` endpoint.

    Args:
        base_url: Provider base URL.
        api_key: API key used as ``Authorization: Bearer <key>`` when provided.
        api_key_env_var: Environment variable fallback for API key.
        models_path: Relative endpoint path for model listing.
        timeout_seconds: HTTP timeout for the discovery request.

    Returns:
        Ordered unique model IDs.
    """
    resolved_api_key = _resolve_optional_api_key(
        api_key=api_key,
        api_key_env_var=api_key_env_var,
    )
    response_payload = _request_models_payload(
        base_url=base_url,
        models_path=models_path,
        api_key=resolved_api_key,
        timeout_seconds=timeout_seconds,
    )
    return extract_model_ids(response_payload)


def extract_model_ids(payload: object) -> Sequence[str]:
    """
    Extract model IDs from common provider ``/models`` payload shapes.

    Supported payloads:
    - ``{\"data\": [{\"id\": \"...\"}, ...]}``
    - ``{\"models\": [{\"id\": \"...\"}, ...]}``
    - ``[{\"id\": \"...\"}, ...]``
    - ``[\"model-a\", \"model-b\", ...]``
    """
    candidates: Sequence[object]
    if isinstance(payload, dict):
        data_candidates = payload.get("data")
        models_candidates = payload.get("models")
        if isinstance(data_candidates, list):
            candidates = data_candidates
        elif isinstance(models_candidates, list):
            candidates = models_candidates
        else:
            raise ValueError("Provider response must include a list in 'data' or 'models'.")
    elif isinstance(payload, list):
        candidates = payload
    else:
        raise ValueError("Provider response must be a dict or list.")

    discovered: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            raw_id = item.get("id")
            if not isinstance(raw_id, str):
                continue
            model_id = raw_id.strip()
        else:
            continue

        if not model_id or model_id in seen:
            continue
        discovered.append(model_id)
        seen.add(model_id)

    if not discovered:
        raise ValueError("No model IDs were found in the provider response.")

    return tuple(discovered)


def generate_models_file(
    *,
    provider_name: str,
    base_url: str,
    model_ids: Sequence[str],
    output_path: str | Path = DEFAULT_GENERATED_MODELS_PATH,
    api_key_env_var: str = DEFAULT_API_KEY_ENV_VAR,
) -> Path:
    """
    Upsert generated provider models into a Python module.

    The output module always contains a ``Models`` class and preserves generated
    blocks for providers other than ``provider_name``.
    """
    provider_alias = _validate_provider_name(provider_name)
    output = Path(output_path)
    existing_content = output.read_text(encoding="utf-8") if output.exists() else ""

    content_with_support = _upsert_support_block(existing_content)
    provider_block = _render_provider_block(
        provider_name=provider_alias,
        base_url=base_url.rstrip("/"),
        model_ids=model_ids,
        api_key_env_var=api_key_env_var,
        existing_content=content_with_support,
    )
    next_content = upsert_provider_block(
        content=content_with_support,
        provider_name=provider_alias,
        provider_block=provider_block,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(next_content.rstrip() + "\n", encoding="utf-8")
    return output


def upsert_provider_block(
    *,
    content: str,
    provider_name: str,
    provider_block: str,
) -> str:
    """
    Replace or append a provider-generated block while preserving others.
    """
    start_marker = _provider_block_start(provider_name)
    end_marker = _provider_block_end(provider_name)
    return _upsert_block(
        content=content,
        start_marker=start_marker,
        end_marker=end_marker,
        block=provider_block.strip(),
        prepend_if_missing=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate explicit lazy pyflow model bindings from a provider /models endpoint."
        )
    )
    parser.add_argument(
        "provider",
        help=(
            "Short Python identifier used under Models.<provider>. "
            "Keep this short because generated aliases include it."
        ),
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Provider base URL (for example: https://api.openai.com/v1).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "API key used to call /models. If omitted, the value from --api-key-env-var "
            "is used when present."
        ),
    )
    parser.add_argument(
        "--api-key-env-var",
        default=DEFAULT_API_KEY_ENV_VAR,
        help="Environment variable fallback for API key (default: API_KEY).",
    )
    parser.add_argument(
        "--models-path",
        default="/models",
        help="Relative discovery endpoint path (default: /models).",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_GENERATED_MODELS_PATH),
        help="Target Python module path for generated models.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout in seconds for provider discovery request.",
    )
    args = parser.parse_args(argv)

    generated_path = generate_models_from_provider(
        provider_name=args.provider,
        base_url=args.base_url,
        output_path=args.output,
        api_key=args.api_key,
        api_key_env_var=args.api_key_env_var,
        models_path=args.models_path,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        "Generated model bindings at "
        f"{generated_path} for provider '{args.provider}'."
    )
    return 0


def _request_models_payload(
    *,
    base_url: str,
    models_path: str,
    api_key: str | None,
    timeout_seconds: float,
) -> object:
    endpoint = _join_url(base_url.rstrip("/"), models_path)
    headers = {"Accept": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = request.Request(endpoint, headers=headers, method="GET")

    with request.urlopen(http_request, timeout=timeout_seconds) as response:
        raw_payload = response.read()
    return json.loads(raw_payload.decode("utf-8"))


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url}/{path.lstrip('/')}"


def _resolve_optional_api_key(
    *,
    api_key: str | SecretStr | None,
    api_key_env_var: str,
) -> str | None:
    if isinstance(api_key, SecretStr):
        key_value = api_key.get_secret_value().strip()
    elif isinstance(api_key, str):
        key_value = api_key.strip()
    else:
        key_value = ""

    if key_value:
        return key_value

    env_value = os.getenv(api_key_env_var, "").strip()
    return env_value or None


def _validate_provider_name(value: str) -> str:
    alias = _sanitize_identifier(value)
    if alias != value:
        raise ValueError(
            "Provider name must already be a valid lowercase Python identifier "
            "(letters, digits, underscores, cannot start with a digit)."
        )
    return alias


def _upsert_support_block(content: str) -> str:
    return _upsert_block(
        content=content,
        start_marker=_SUPPORT_BLOCK_START,
        end_marker=_SUPPORT_BLOCK_END,
        block=_render_support_block(),
        prepend_if_missing=True,
    )


def _render_support_block() -> str:
    return "\n".join(
        [
            _SUPPORT_BLOCK_START,
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass",
            "import os",
            "",
            "from pydantic import SecretStr",
            "",
            "from pyflow.model import AIModel",
            "",
            "",
            "@dataclass(frozen=True, kw_only=True)",
            "class _LazyModelReference:",
            "    model_id: str",
            "    base_url: str",
            "    api_key_env_var: str = \"API_KEY\"",
            "",
            "    def __call__(",
            "        self,",
            "        *,",
            "        api_key: str | SecretStr | None = None,",
            "        max_input_tokens: int | None = None,",
            "        max_output_tokens: int | None = None,",
            "    ) -> AIModel:",
            "        resolved_key = _resolve_api_key(",
            "            api_key=api_key,",
            "            api_key_env_var=self.api_key_env_var,",
            "        )",
            "        return AIModel(",
            "            name=self.model_id,",
            "            base_url=self.base_url,",
            "            api_key=resolved_key,",
            "            max_input_tokens=max_input_tokens,",
            "            max_output_tokens=max_output_tokens,",
            "        )",
            "",
            "    def build(",
            "        self,",
            "        *,",
            "        api_key: str | SecretStr | None = None,",
            "        max_input_tokens: int | None = None,",
            "        max_output_tokens: int | None = None,",
            "    ) -> AIModel:",
            "        return self(",
            "            api_key=api_key,",
            "            max_input_tokens=max_input_tokens,",
            "            max_output_tokens=max_output_tokens,",
            "        )",
            "",
            "",
            "def _resolve_api_key(*, api_key: str | SecretStr | None, api_key_env_var: str) -> SecretStr:",
            "    if isinstance(api_key, SecretStr):",
            "        value = api_key.get_secret_value().strip()",
            "        if value:",
            "            return api_key",
            "    if isinstance(api_key, str):",
            "        value = api_key.strip()",
            "        if value:",
            "            return SecretStr(value)",
            "    env_value = os.getenv(api_key_env_var, \"\").strip()",
            "    if env_value:",
            "        return SecretStr(env_value)",
            "    raise ValueError(",
            "        \"Missing API key. Pass api_key=... explicitly or set \"",
            "        f\"{api_key_env_var} in the environment.\"",
            "    )",
            "",
            "",
            "class Models:",
            "    \"\"\"Generated provider model registry. Regenerate with pyflow.model_generator.\"\"\"",
            "    pass",
            _SUPPORT_BLOCK_END,
        ]
    )


def _render_provider_block(
    *,
    provider_name: str,
    base_url: str,
    model_ids: Sequence[str],
    api_key_env_var: str,
    existing_content: str,
) -> str:
    entries = _build_model_entries(model_ids)
    namespace_tree = _build_namespace_tree(entries)
    class_blocks, root_group_bindings = _render_nested_namespace_blocks(
        provider_name=provider_name,
        tree=namespace_tree,
        base_url=base_url,
        api_key_env_var=api_key_env_var,
    )

    provider_class_name = f"_{_pascal_case(provider_name)}ProviderModels"
    provider_lines: list[str] = [f"class {provider_class_name}:"]
    provider_body: list[str] = []

    for group_name, class_name in root_group_bindings:
        provider_body.append(f"    {group_name}: {class_name} = {class_name}()")

    for entry in entries:
        provider_body.append(
            "    "
            + _render_model_assignment_line(
                alias=entry.flat_alias,
                model_id=entry.model_id,
                base_url=base_url,
                api_key_env_var=api_key_env_var,
            )
        )

    if not provider_body:
        provider_body.append("    pass")

    provider_lines.extend(provider_body)

    existing_global_aliases = _collect_existing_global_aliases(
        content=existing_content,
        excluding_provider=provider_name,
    )
    models_bindings: list[str] = [
        f"Models.{provider_name} = {provider_class_name}()",
    ]
    existing_global_aliases.add(provider_name)

    for entry in entries:
        provider_prefixed_alias = f"{provider_name}_{entry.flat_alias}"
        models_bindings.append(
            f"Models.{provider_prefixed_alias} = Models.{provider_name}.{entry.flat_alias}"
        )
        existing_global_aliases.add(provider_prefixed_alias)

        if entry.flat_alias not in existing_global_aliases:
            models_bindings.append(
                f"Models.{entry.flat_alias} = Models.{provider_name}.{entry.flat_alias}"
            )
            existing_global_aliases.add(entry.flat_alias)

    block_lines = [
        _provider_block_start(provider_name),
        *class_blocks,
        "",
        *provider_lines,
        "",
        *models_bindings,
        _provider_block_end(provider_name),
    ]
    return "\n".join(block_lines).rstrip()


def _build_model_entries(model_ids: Sequence[str]) -> Sequence[_ModelEntry]:
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for model_id in model_ids:
        normalized = model_id.strip()
        if not normalized or normalized in seen_ids:
            continue
        ordered_ids.append(normalized)
        seen_ids.add(normalized)

    if not ordered_ids:
        raise ValueError("At least one non-empty model ID is required.")

    flat_aliases: list[str] = []
    used_flat_aliases: set[str] = set()
    for model_id in ordered_ids:
        candidate = _sanitize_identifier(model_id)
        flat_alias = _unique_alias(candidate, used_flat_aliases)
        flat_aliases.append(flat_alias)
        used_flat_aliases.add(flat_alias)

    nested_paths: list[Sequence[str]] = []
    used_paths: set[tuple[str, ...]] = set()
    for model_id in ordered_ids:
        nested_path = _nested_path_for_model(model_id)
        if len(nested_path) >= 2:
            unique_path = _unique_nested_path(nested_path, used_paths)
            nested_paths.append(unique_path)
            used_paths.add(tuple(unique_path))
        else:
            nested_paths.append(())

    return tuple(
        _ModelEntry(
            model_id=model_id,
            flat_alias=flat_alias,
            nested_path=path,
        )
        for model_id, flat_alias, path in zip(
            ordered_ids,
            flat_aliases,
            nested_paths,
            strict=True,
        )
    )


def _nested_path_for_model(model_id: str) -> Sequence[str]:
    raw_tokens = [token for token in re.split(r"[\/._-]+", model_id) if token]
    if len(raw_tokens) < 2:
        return ()

    aliases: list[str] = []
    for token in raw_tokens:
        token_alias = _sanitize_nested_token(token)
        if token_alias:
            aliases.append(token_alias)
    return tuple(aliases)


def _sanitize_nested_token(token: str) -> str:
    lowered = token.strip().lower()
    if not lowered:
        return ""
    size_match = re.fullmatch(r"(\d+)([bkmt])", lowered)
    if size_match is not None:
        lowered = f"{size_match.group(2)}{size_match.group(1)}"
    alias = _sanitize_identifier(lowered)
    return alias


def _sanitize_identifier(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    if not lowered:
        lowered = "model"
    if lowered[0].isdigit():
        lowered = f"n_{lowered}"
    if keyword.iskeyword(lowered):
        lowered = f"{lowered}_value"
    return lowered


def _unique_alias(candidate: str, used_aliases: set[str]) -> str:
    if candidate not in used_aliases:
        return candidate
    suffix = 2
    while True:
        resolved = f"{candidate}_{suffix}"
        if resolved not in used_aliases:
            return resolved
        suffix += 1


def _unique_nested_path(
    path: Sequence[str],
    used_paths: set[tuple[str, ...]],
) -> Sequence[str]:
    as_tuple = tuple(path)
    if as_tuple not in used_paths:
        return as_tuple

    base_segments = list(path[:-1])
    leaf = path[-1]
    suffix = 2
    while True:
        updated = tuple((*base_segments, f"{leaf}_{suffix}"))
        if updated not in used_paths:
            return updated
        suffix += 1


def _build_namespace_tree(entries: Sequence[_ModelEntry]) -> _NamespaceNode:
    root = _NamespaceNode()
    for entry in entries:
        if len(entry.nested_path) < 2:
            continue
        node = root
        for segment in entry.nested_path:
            node = node.children.setdefault(segment, _NamespaceNode())
        node.model = entry
    return root


def _render_nested_namespace_blocks(
    *,
    provider_name: str,
    tree: _NamespaceNode,
    base_url: str,
    api_key_env_var: str,
) -> tuple[Sequence[str], Sequence[tuple[str, str]]]:
    blocks: list[str] = []
    root_group_bindings: list[tuple[str, str]] = []

    def visit(node: _NamespaceNode, path: Sequence[str]) -> str:
        class_name = _namespace_class_name(provider_name, path)
        child_lines: list[str] = []

        if node.model is not None:
            child_lines.append(
                "    "
                + _render_model_assignment_line(
                    alias="model",
                    model_id=node.model.model_id,
                    base_url=base_url,
                    api_key_env_var=api_key_env_var,
                )
            )

        for child_name in sorted(node.children):
            child_node = node.children[child_name]
            if child_node.children:
                nested_class_name = visit(child_node, (*path, child_name))
                child_lines.append(
                    f"    {child_name}: {nested_class_name} = {nested_class_name}()"
                )
                continue

            if child_node.model is not None:
                child_lines.append(
                    "    "
                    + _render_model_assignment_line(
                        alias=child_name,
                        model_id=child_node.model.model_id,
                        base_url=base_url,
                        api_key_env_var=api_key_env_var,
                    )
                )

        if not child_lines:
            child_lines.append("    pass")

        class_block = "\n".join([f"class {class_name}:"] + child_lines)
        blocks.append(class_block)
        return class_name

    for group_name in sorted(tree.children):
        group_node = tree.children[group_name]
        if group_node.children:
            class_name = visit(group_node, (group_name,))
            root_group_bindings.append((group_name, class_name))
            continue
        if group_node.model is None:
            continue
        class_name = _namespace_class_name(provider_name, (group_name,))
        block_lines = [
            f"class {class_name}:",
            "    "
            + _render_model_assignment_line(
                alias="model",
                model_id=group_node.model.model_id,
                base_url=base_url,
                api_key_env_var=api_key_env_var,
            ),
        ]
        blocks.append("\n".join(block_lines))
        root_group_bindings.append((group_name, class_name))

    return tuple(blocks), tuple(root_group_bindings)


def _namespace_class_name(provider_name: str, path: Sequence[str]) -> str:
    tokens = [provider_name, *path, "models"]
    return "_" + "".join(_pascal_case(token) for token in tokens)


def _pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_") if part) or "Value"


def _render_model_assignment_line(
    *,
    alias: str,
    model_id: str,
    base_url: str,
    api_key_env_var: str,
) -> str:
    return (
        f"{alias}: _LazyModelReference = _LazyModelReference("
        f"model_id={model_id!r}, "
        f"base_url={base_url!r}, "
        f"api_key_env_var={api_key_env_var!r})"
    )


def _collect_existing_global_aliases(
    *,
    content: str,
    excluding_provider: str,
) -> set[str]:
    content_without_provider = _remove_provider_block(content, excluding_provider)
    aliases = set(
        re.findall(r"(?m)^Models\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=", content_without_provider)
    )
    aliases.add("Models")
    return aliases


def _remove_provider_block(content: str, provider_name: str) -> str:
    start_marker = _provider_block_start(provider_name)
    end_marker = _provider_block_end(provider_name)
    pattern = (
        f"{re.escape(start_marker)}"
        r"\n.*?\n"
        f"{re.escape(end_marker)}"
    )
    return re.sub(pattern, "", content, flags=re.DOTALL)


def _upsert_block(
    *,
    content: str,
    start_marker: str,
    end_marker: str,
    block: str,
    prepend_if_missing: bool,
) -> str:
    pattern = (
        f"{re.escape(start_marker)}"
        r"\n.*?\n"
        f"{re.escape(end_marker)}"
    )

    if re.search(pattern, content, flags=re.DOTALL):
        return re.sub(pattern, block, content, flags=re.DOTALL)

    if not content.strip():
        return block + "\n"

    if prepend_if_missing:
        return block.rstrip() + "\n\n" + content.lstrip()
    return content.rstrip() + "\n\n" + block.rstrip() + "\n"


def _provider_block_start(provider_name: str) -> str:
    return f"{_PROVIDER_BLOCK_START_PREFIX}{provider_name}"


def _provider_block_end(provider_name: str) -> str:
    return f"{_PROVIDER_BLOCK_END_PREFIX}{provider_name}"


if __name__ == "__main__":
    raise SystemExit(main())
