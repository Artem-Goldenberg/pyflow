from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib import error, request

from pydantic import SecretStr


DEFAULT_GENERATED_MODELS_PATH = Path("pyflow/_generated/models.py")
DEFAULT_API_KEY_ENV_VAR = "API_KEY"
DEFAULT_HTTP_USER_AGENT = "pyflow/0.1"

_SUPPORT_BLOCK_START = "# >>> PYFLOW_MODELS_SUPPORT_START"
_SUPPORT_BLOCK_END = "# <<< PYFLOW_MODELS_SUPPORT_END"
_PROVIDER_BLOCK_START_PREFIX = "# >>> PYFLOW_PROVIDER_MODELS_START: "
_PROVIDER_BLOCK_END_PREFIX = "# <<< PYFLOW_PROVIDER_MODELS_END: "
_PROVIDER_SPEC_COMMENT_PREFIX = "# PYFLOW_PROVIDER_SPEC "


@dataclass(frozen=True, kw_only=True)
class _ModelEntry:
    model_id: str
    provider_alias: str
    model_alias: str | None


@dataclass(frozen=True, kw_only=True)
class _ProviderSpec:
    provider_name: str
    base_url: str
    api_key_env_var: str
    model_ids: Sequence[str]


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
    provider_specs = _extract_provider_specs(existing_content)
    provider_specs[provider_alias] = _ProviderSpec(
        provider_name=provider_alias,
        base_url=base_url.rstrip("/"),
        api_key_env_var=api_key_env_var,
        model_ids=_normalize_model_ids(model_ids),
    )
    next_content = _render_models_module(tuple(provider_specs.values()))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(next_content.rstrip() + "\n", encoding="utf-8")
    return output


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
    headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_HTTP_USER_AGENT,
    }
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = request.Request(endpoint, headers=headers, method="GET")

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_payload = response.read()
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        message = f"HTTP Error {exc.code}: {exc.reason}"
        if error_body:
            message = f"{message}\n{error_body}"
        raise RuntimeError(
            f"Provider model discovery request failed for {endpoint}.\n{message}"
        ) from exc
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


def _render_support_block() -> str:
    return "\n".join(
        [
            _SUPPORT_BLOCK_START,
            "from __future__ import annotations",
            "",
            "import os",
            "",
            "from pydantic import SecretStr",
            "",
            "from pyflow.model import Model",
            "",
            "",
            "def _create_model(*, model_id: str, base_url: str, api_key_env_var: str) -> Model:",
            "    resolved_key = _resolve_api_key(",
            "        api_key=None,",
            "        api_key_env_var=api_key_env_var,",
            "    )",
            "    return Model.from_api(",
            "        name=model_id,",
            "        base_url=base_url,",
            "        api_key=resolved_key,",
            "    )",
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
            _SUPPORT_BLOCK_END,
        ]
    )


def _render_models_module(provider_specs: Sequence[_ProviderSpec]) -> str:
    lines = [
        _render_support_block(),
        "",
        "",
        "class Models:",
        "    \"\"\"Generated provider model registry. Regenerate with pyflow.model_generator.\"\"\"",
    ]

    if not provider_specs:
        lines.append("    pass")
        return "\n".join(lines).rstrip()

    for provider_spec in provider_specs:
        lines.append("")
        lines.extend(_render_provider_block(provider_spec))

    return "\n".join(lines).rstrip()


def _render_provider_block(provider_spec: _ProviderSpec) -> Sequence[str]:
    entries = _build_model_entries(
        provider_name=provider_spec.provider_name,
        model_ids=provider_spec.model_ids,
    )
    provider_class_name = f"_{_pascal_case(provider_spec.provider_name)}ProviderModels"
    grouped_entries = _group_entries_by_provider_alias(entries)
    helper_blocks: list[str] = []

    for provider_alias, family_entries in grouped_entries.items():
        if not _is_family_group(family_entries):
            continue
        helper_blocks.extend(
            _render_family_class_block(
                provider_name=provider_spec.provider_name,
                family_alias=provider_alias,
                entries=family_entries,
                base_url=provider_spec.base_url,
                api_key_env_var=provider_spec.api_key_env_var,
            )
        )
        helper_blocks.append("")

    helper_blocks.extend(
        _render_provider_class_block(
            provider_name=provider_spec.provider_name,
            provider_class_name=provider_class_name,
            grouped_entries=grouped_entries,
            base_url=provider_spec.base_url,
            api_key_env_var=provider_spec.api_key_env_var,
        )
    )

    metadata_comment = _render_provider_spec_comment(provider_spec)
    return (
        f"    {_provider_block_start(provider_spec.provider_name)}",
        f"    {metadata_comment}",
        *helper_blocks,
        f"    {provider_spec.provider_name}: {provider_class_name} = {provider_class_name}()",
        f"    {_provider_block_end(provider_spec.provider_name)}",
    )


def _build_model_entries(
    *,
    provider_name: str,
    model_ids: Sequence[str],
) -> Sequence[_ModelEntry]:
    ordered_ids = _normalize_model_ids(model_ids)
    raw_plans = [
        (model_id, *_classify_model_id(provider_name=provider_name, model_id=model_id))
        for model_id in ordered_ids
    ]
    direct_provider_aliases = {
        provider_alias
        for _, provider_alias, model_alias in raw_plans
        if model_alias is None
    }
    planned_entries = [
        (
            model_id,
            f"{provider_alias}_{model_alias}",
            None,
        )
        if model_alias is not None and provider_alias in direct_provider_aliases
        else (model_id, provider_alias, model_alias)
        for model_id, provider_alias, model_alias in raw_plans
    ]
    family_aliases = {
        provider_alias
        for _, provider_alias, model_alias in planned_entries
        if model_alias is not None
    }
    used_provider_aliases = set(family_aliases)
    used_model_aliases: dict[str, set[str]] = {
        provider_alias: set()
        for provider_alias in family_aliases
    }
    entries: list[_ModelEntry] = []

    for model_id, provider_alias_candidate, model_alias_candidate in planned_entries:
        if model_alias_candidate is None:
            provider_alias = _unique_alias(provider_alias_candidate, used_provider_aliases)
            used_provider_aliases.add(provider_alias)
            entries.append(
                _ModelEntry(
                    model_id=model_id,
                    provider_alias=provider_alias,
                    model_alias=None,
                )
            )
            continue

        concrete_alias = _unique_alias(
            model_alias_candidate,
            used_model_aliases[provider_alias_candidate],
        )
        used_model_aliases[provider_alias_candidate].add(concrete_alias)
        entries.append(
            _ModelEntry(
                model_id=model_id,
                provider_alias=provider_alias_candidate,
                model_alias=concrete_alias,
            )
        )

    return tuple(entries)


def _classify_model_id(*, provider_name: str, model_id: str) -> tuple[str, str | None]:
    segments = [segment for segment in model_id.split("/") if segment]
    provider_alias = _sanitize_identifier(provider_name)
    target = segments[-1] if segments else model_id

    if len(segments) > 1 and _sanitize_identifier(segments[0]) == provider_alias:
        return (_sanitize_identifier(target), None)

    raw_tokens = [token for token in re.split(r"[._-]+", target) if token]
    if len(raw_tokens) < 2:
        return (_sanitize_identifier(target), None)

    family_alias = _normalize_family_alias(raw_tokens[0])
    concrete_tokens = list(raw_tokens[1:])
    while len(concrete_tokens) > 1 and re.fullmatch(r"\d+", concrete_tokens[0]) is not None:
        concrete_tokens.pop(0)

    concrete_alias = _alias_from_tokens(concrete_tokens)
    if concrete_alias == "model":
        return (_sanitize_identifier(target), None)
    return (family_alias, concrete_alias)


def _normalize_family_alias(token: str) -> str:
    lowered = token.strip().lower()
    match = re.fullmatch(r"([a-z]+)\d+", lowered)
    if match is not None:
        lowered = match.group(1)
    return _sanitize_identifier(lowered)


def _alias_from_tokens(tokens: Sequence[str]) -> str:
    aliases = [_sanitize_model_token(token) for token in tokens]
    filtered_aliases = [alias for alias in aliases if alias]
    if not filtered_aliases:
        return "model"
    return "_".join(filtered_aliases)


def _sanitize_model_token(token: str) -> str:
    lowered = token.strip().lower()
    if not lowered:
        return ""
    size_match = re.fullmatch(r"(\d+)([bkmt])", lowered)
    if size_match is not None:
        lowered = f"{size_match.group(2)}{size_match.group(1)}"
    return _sanitize_identifier(lowered)


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


def _normalize_model_ids(model_ids: Sequence[str]) -> Sequence[str]:
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

    return tuple(ordered_ids)


def _group_entries_by_provider_alias(
    entries: Sequence[_ModelEntry],
) -> dict[str, list[_ModelEntry]]:
    grouped: dict[str, list[_ModelEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.provider_alias, []).append(entry)
    return grouped


def _is_family_group(entries: Sequence[_ModelEntry]) -> bool:
    return any(entry.model_alias is not None for entry in entries)


def _render_family_class_block(
    *,
    provider_name: str,
    family_alias: str,
    entries: Sequence[_ModelEntry],
    base_url: str,
    api_key_env_var: str,
) -> Sequence[str]:
    class_name = _family_class_name(provider_name=provider_name, family_alias=family_alias)
    lines = [f"    class {class_name}:"]
    body: list[str] = []

    for index, entry in enumerate(entries):
        if entry.model_alias is None:
            continue
        if index > 0 and body:
            body.append("")
        body.extend(
            _render_model_property_block(
                property_name=entry.model_alias,
                cache_name=f"_{entry.model_alias}",
                model_id=entry.model_id,
                base_url=base_url,
                api_key_env_var=api_key_env_var,
                indent="        ",
            )
        )

    if not body:
        body.append("        pass")

    return (*lines, *body)


def _render_provider_class_block(
    *,
    provider_name: str,
    provider_class_name: str,
    grouped_entries: dict[str, list[_ModelEntry]],
    base_url: str,
    api_key_env_var: str,
) -> Sequence[str]:
    lines = [f"    class {provider_class_name}:"]
    body: list[str] = []

    for provider_alias in sorted(grouped_entries):
        entries = grouped_entries[provider_alias]
        if body:
            body.append("")

        if _is_family_group(entries):
            family_class_name = _family_class_name(
                provider_name=provider_name,
                family_alias=provider_alias,
            )
            body.extend(
                _render_namespace_property_block(
                    property_name=provider_alias,
                    cache_name=f"_{provider_alias}",
                    namespace_class_name=family_class_name,
                    indent="        ",
                )
            )
            continue

        entry = entries[0]
        body.extend(
            _render_model_property_block(
                property_name=entry.provider_alias,
                cache_name=f"_{entry.provider_alias}",
                model_id=entry.model_id,
                base_url=base_url,
                api_key_env_var=api_key_env_var,
                indent="        ",
            )
        )

    if not body:
        body.append("        pass")

    return (*lines, *body)


def _render_namespace_property_block(
    *,
    property_name: str,
    cache_name: str,
    namespace_class_name: str,
    indent: str,
) -> Sequence[str]:
    return (
        f"{indent}{cache_name}: Models.{namespace_class_name} | None = None",
        "",
        f"{indent}@property",
        f"{indent}def {property_name}(self) -> Models.{namespace_class_name}:",
        f"{indent}    if self.{cache_name} is None:",
        f"{indent}        self.{cache_name} = Models.{namespace_class_name}()",
        f"{indent}    return self.{cache_name}",
    )


def _render_model_property_block(
    *,
    property_name: str,
    cache_name: str,
    model_id: str,
    base_url: str,
    api_key_env_var: str,
    indent: str,
) -> Sequence[str]:
    return (
        f"{indent}{cache_name}: Model | None = None",
        "",
        f"{indent}@property",
        f"{indent}def {property_name}(self) -> Model:",
        f"{indent}    if self.{cache_name} is None:",
        f"{indent}        self.{cache_name} = _create_model(",
        f"{indent}            model_id={model_id!r},",
        f"{indent}            base_url={base_url!r},",
        f"{indent}            api_key_env_var={api_key_env_var!r},",
        f"{indent}        )",
        f"{indent}    return self.{cache_name}",
    )


def _family_class_name(*, provider_name: str, family_alias: str) -> str:
    return f"_{_pascal_case(provider_name)}{_pascal_case(family_alias)}Models"


def _pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_") if part) or "Value"


def _render_provider_spec_comment(provider_spec: _ProviderSpec) -> str:
    spec_payload = json.dumps(
        {
            "base_url": provider_spec.base_url,
            "api_key_env_var": provider_spec.api_key_env_var,
            "model_ids": list(provider_spec.model_ids),
        },
        sort_keys=True,
    )
    return f"{_PROVIDER_SPEC_COMMENT_PREFIX}{spec_payload}"


def _extract_provider_specs(content: str) -> dict[str, _ProviderSpec]:
    provider_specs: dict[str, _ProviderSpec] = {}
    block_pattern = re.compile(
        rf"(?ms)^[ \t]*{re.escape(_PROVIDER_BLOCK_START_PREFIX)}"
        r"(?P<provider>[a-zA-Z_][a-zA-Z0-9_]*)[ \t]*\n"
        r"(?P<body>.*?)"
        rf"^[ \t]*{re.escape(_PROVIDER_BLOCK_END_PREFIX)}(?P=provider)[ \t]*$"
    )
    for match in block_pattern.finditer(content):
        provider_name = match.group("provider")
        provider_spec = _parse_provider_block(
            provider_name=provider_name,
            block_body=match.group("body"),
        )
        if provider_spec is not None:
            provider_specs[provider_name] = provider_spec
    return provider_specs


def _parse_provider_block(
    *,
    provider_name: str,
    block_body: str,
) -> _ProviderSpec | None:
    metadata_spec = _parse_provider_metadata_comment(
        provider_name=provider_name,
        block_body=block_body,
    )
    if metadata_spec is not None:
        return metadata_spec

    parsed = ast.parse(textwrap.dedent(block_body))
    model_ids: list[str] = []
    seen_ids: set[str] = set()
    base_url: str | None = None
    api_key_env_var: str | None = None

    for node in ast.walk(parsed):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in {
            "_GeneratedModel",
            "_LazyModelReference",
        }:
            continue

        keyword_nodes = {
            keyword_node.arg: keyword_node.value
            for keyword_node in node.keywords
            if keyword_node.arg is not None
        }
        model_id = _string_literal(keyword_nodes.get("model_id"))
        base_url_value = _string_literal(keyword_nodes.get("base_url"))
        api_key_env_var_value = _string_literal(keyword_nodes.get("api_key_env_var"))
        if (
            model_id is None
            or base_url_value is None
            or api_key_env_var_value is None
        ):
            continue

        if model_id not in seen_ids:
            model_ids.append(model_id)
            seen_ids.add(model_id)

        if base_url is None:
            base_url = base_url_value
        if api_key_env_var is None:
            api_key_env_var = api_key_env_var_value

    if not model_ids or base_url is None or api_key_env_var is None:
        return None

    return _ProviderSpec(
        provider_name=provider_name,
        base_url=base_url,
        api_key_env_var=api_key_env_var,
        model_ids=tuple(model_ids),
    )


def _parse_provider_metadata_comment(
    *,
    provider_name: str,
    block_body: str,
) -> _ProviderSpec | None:
    match = re.search(
        rf"(?m)^[ \t]*{re.escape(_PROVIDER_SPEC_COMMENT_PREFIX)}(?P<payload>{{.*}})$",
        block_body,
    )
    if match is None:
        return None

    payload = json.loads(match.group("payload"))
    if not isinstance(payload, dict):
        return None

    base_url = payload.get("base_url")
    api_key_env_var = payload.get("api_key_env_var")
    model_ids = payload.get("model_ids")
    if (
        not isinstance(base_url, str)
        or not isinstance(api_key_env_var, str)
        or not isinstance(model_ids, list)
        or any(not isinstance(model_id, str) for model_id in model_ids)
    ):
        return None

    return _ProviderSpec(
        provider_name=provider_name,
        base_url=base_url,
        api_key_env_var=api_key_env_var,
        model_ids=tuple(model_ids),
    )


def _string_literal(node: ast.AST | None) -> str | None:
    if node is None:
        return None

    try:
        value = ast.literal_eval(node)
    except (SyntaxError, ValueError):
        return None

    if isinstance(value, str):
        return value
    return None


def _provider_block_start(provider_name: str) -> str:
    return f"{_PROVIDER_BLOCK_START_PREFIX}{provider_name}"


def _provider_block_end(provider_name: str) -> str:
    return f"{_PROVIDER_BLOCK_END_PREFIX}{provider_name}"


if __name__ == "__main__":
    raise SystemExit(main())
