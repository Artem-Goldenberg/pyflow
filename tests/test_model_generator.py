from __future__ import annotations

import importlib.util
import io
import re
import sys
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Sequence
from urllib import error, request

import pytest
from pydantic import SecretStr

import pyflow.model_generator as model_generator
from pyflow import Model


def test_extract_model_ids_supports_common_payload_shapes() -> None:
    openai_style = {
        "data": [
            {"id": "qwen-16b"},
            {"id": "qwen-small-16b"},
            {"id": "qwen-16b"},
        ]
    }
    direct_list = ["gpt-4o-mini", "gpt-4.1"]

    extracted_openai = model_generator.extract_model_ids(openai_style)
    extracted_list = model_generator.extract_model_ids(direct_list)

    assert extracted_openai == ("qwen-16b", "qwen-small-16b")
    assert extracted_list == ("gpt-4o-mini", "gpt-4.1")


def test_generate_models_file_preserves_other_provider_blocks(tmp_path: Path) -> None:
    output = tmp_path / "generated_models.py"

    model_generator.generate_models_file(
        provider_name="first",
        base_url="https://first.example/v1",
        model_ids=("qwen-16b", "qwen-small-16b"),
        output_path=output,
    )
    model_generator.generate_models_file(
        provider_name="second",
        base_url="https://second.example/v1",
        model_ids=("gpt-4o-mini",),
        output_path=output,
    )

    content_before_regen = output.read_text(encoding="utf-8")
    second_provider_block_before = _extract_provider_block(
        content=content_before_regen,
        provider_name="second",
    )

    model_generator.generate_models_file(
        provider_name="first",
        base_url="https://first.example/v2",
        model_ids=("qwen-72b",),
        output_path=output,
    )

    final_content = output.read_text(encoding="utf-8")
    first_provider_block = _extract_provider_block(
        content=final_content,
        provider_name="first",
    )
    second_provider_block_after = _extract_provider_block(
        content=final_content,
        provider_name="second",
    )

    assert "class Models:" in final_content
    assert "    class first:" in final_content
    assert "    first = first()" in final_content
    assert "models = Models()" in final_content
    assert "def b72(self) -> Model:" in first_provider_block
    assert "def b16(self) -> Model:" not in first_provider_block
    assert second_provider_block_after == second_provider_block_before


def test_generate_models_file_upgrades_legacy_provider_blocks(tmp_path: Path) -> None:
    output = tmp_path / "generated_models.py"
    output.write_text(
        "\n".join(
            [
                "# >>> PYFLOW_PROVIDER_MODELS_START: legacy",
                "class _LegacyProviderModels:",
                "    qwen_16b: _LazyModelReference = _LazyModelReference(",
                "        model_id='qwen-16b',",
                "        base_url='https://legacy.example/v1',",
                "        api_key_env_var='API_KEY',",
                "    )",
                "",
                "Models.legacy = _LegacyProviderModels()",
                "# <<< PYFLOW_PROVIDER_MODELS_END: legacy",
            ]
        ),
        encoding="utf-8",
    )

    model_generator.generate_models_file(
        provider_name="legacy",
        base_url="https://legacy.example/v2",
        model_ids=("qwen-72b",),
        output_path=output,
    )

    content = output.read_text(encoding="utf-8")

    assert "class Models:" in content
    assert "class legacy:" in content
    assert "legacy = legacy()" in content
    assert "models = Models()" in content
    assert "_create_model(" in content
    assert "_LazyModelReference(" not in content


def test_generated_models_expose_two_level_namespaces_and_fresh_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "generated_models.py"
    model_generator.generate_models_file(
        provider_name="qw",
        base_url="https://provider.example/v1",
        model_ids=("qwen-16b", "qwen-small-16b"),
        output_path=output,
    )

    generated = _load_module(module_path=output, module_name="generated_models_runtime_test")
    provider_models = generated.models.qw
    family_models = provider_models.qwen

    assert provider_models is generated.models.qw
    assert family_models is provider_models.qwen
    assert not hasattr(provider_models, "qwen_16b")
    assert not hasattr(provider_models, "qwen_small_16b")

    monkeypatch.setenv("API_KEY", "manual-key")
    first_model = family_models.b16
    second_model = family_models.b16
    flat_model = generated.models.qw_qwen_b16
    assert isinstance(first_model, Model)
    assert isinstance(second_model, Model)
    assert isinstance(flat_model, Model)
    assert isinstance(generated.models.qw_qwen_small_b16, Model)
    assert first_model is not second_model
    assert first_model is not flat_model
    first_llm = first_model.inner_llm
    assert first_llm is first_model.inner_llm
    assert first_llm.model == "qwen-16b"
    assert first_llm.base_url == "https://provider.example/v1"
    assert isinstance(first_llm.api_key, SecretStr)
    assert first_llm.api_key.get_secret_value() == "manual-key"

    monkeypatch.setenv("API_KEY", "rotated-key")
    rotated_model = family_models.b16
    rotated_llm = rotated_model.inner_llm
    assert isinstance(rotated_llm.api_key, SecretStr)
    assert rotated_llm.api_key.get_secret_value() == "rotated-key"

    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValueError, match="Missing API key"):
        _ = family_models.small_b16

    monkeypatch.setenv("API_KEY", "from-env")
    small_model = family_models.small_b16
    assert isinstance(small_model, Model)
    env_llm = small_model.inner_llm
    assert env_llm.model == "qwen-small-16b"
    assert isinstance(env_llm.api_key, SecretStr)
    assert env_llm.api_key.get_secret_value() == "from-env"


def test_generated_models_flatten_provider_named_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "generated_models.py"
    model_generator.generate_models_file(
        provider_name="mix",
        base_url="https://provider.example/v1",
        model_ids=("groq/compound", "groq/compound-mini"),
        output_path=output,
    )

    generated = _load_module(module_path=output, module_name="generated_models_branch_test")

    monkeypatch.setenv("API_KEY", "manual-key")
    assert isinstance(generated.models.mix.compound, Model)
    assert isinstance(generated.models.mix.compound_mini, Model)
    assert isinstance(generated.models.mix_compound, Model)
    assert isinstance(generated.models.mix_compound_mini, Model)
    assert not hasattr(generated.models.mix, "groq")


def test_generated_models_flatten_repeated_family_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "generated_models.py"
    model_generator.generate_models_file(
        provider_name="groq",
        base_url="https://provider.example/v1",
        model_ids=("qwen/qwen3-32b", "groq/compound-mini"),
        output_path=output,
    )

    generated = _load_module(module_path=output, module_name="generated_models_flatten_test")

    monkeypatch.setenv("API_KEY", "manual-key")
    assert isinstance(generated.models.groq.qwen3.b32, Model)
    assert isinstance(generated.models.groq.compound_mini, Model)
    assert isinstance(generated.models.groq_qwen3_b32, Model)
    assert not hasattr(generated.models.groq, "qwen")
    assert not hasattr(generated.models.groq.qwen3, "qwen3_b32")


def test_generate_models_from_provider_uses_api_key_only_for_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "generated_models.py"
    captured: dict[str, object] = {}

    def fake_discover_provider_models(
        *,
        base_url: str,
        api_key: str | SecretStr | None = None,
        api_key_env_var: str = model_generator.DEFAULT_API_KEY_ENV_VAR,
        models_path: str = "/models",
        timeout_seconds: float = 30.0,
    ) -> Sequence[str]:
        captured.update(
            base_url=base_url,
            api_key=api_key,
            api_key_env_var=api_key_env_var,
            models_path=models_path,
            timeout_seconds=timeout_seconds,
        )
        return ("qwen-16b",)

    monkeypatch.setattr(
        model_generator,
        "discover_provider_models",
        fake_discover_provider_models,
    )

    model_generator.generate_models_from_provider(
        provider="qw",
        base_url="https://provider.example/v1",
        output_path=output,
        api_key="discovery-token",
        api_key_env_var="RUNTIME_KEY",
    )

    content = output.read_text(encoding="utf-8")

    assert captured == {
        "base_url": "https://provider.example/v1",
        "api_key": "discovery-token",
        "api_key_env_var": "RUNTIME_KEY",
        "models_path": "/models",
        "timeout_seconds": 30.0,
    }
    assert "discovery-token" not in content
    assert "RUNTIME_KEY" in content


def test_discover_provider_models_calls_models_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(
        http_request: request.Request,
        timeout: float,
    ) -> _FakeHTTPResponse:
        captured["url"] = http_request.full_url
        captured["auth"] = http_request.headers.get("Authorization")
        captured["user_agent"] = http_request.headers.get("User-agent")
        captured["timeout"] = timeout
        return _FakeHTTPResponse(
            b'{"data":[{"id":"first-model"},{"id":"second-model"}]}'
        )

    monkeypatch.setattr(model_generator.request, "urlopen", fake_urlopen)

    discovered = model_generator.discover_provider_models(
        base_url="https://provider.example/v1/",
        api_key="test-token",
        models_path="/models",
        timeout_seconds=12.5,
    )

    assert discovered == ("first-model", "second-model")
    assert captured["url"] == "https://provider.example/v1/models"
    assert captured["auth"] == "Bearer test-token"
    assert captured["user_agent"] == model_generator.DEFAULT_HTTP_USER_AGENT
    assert captured["timeout"] == 12.5


def test_discover_provider_models_surfaces_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        http_request: request.Request,
        timeout: float,
    ) -> _FakeHTTPResponse:
        raise error.HTTPError(
            url=http_request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=Message(),
            fp=io.BytesIO(b'{"detail":"browser_signature_banned"}'),
        )

    monkeypatch.setattr(model_generator.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="browser_signature_banned"):
        model_generator.discover_provider_models(
            base_url="https://provider.example/v1",
            api_key="test-token",
        )


def _extract_provider_block(*, content: str, provider_name: str) -> str:
    start_marker = f"# >>> PYFLOW_PROVIDER_MODELS_START: {provider_name}"
    end_marker = f"# <<< PYFLOW_PROVIDER_MODELS_END: {provider_name}"
    pattern = (
        r"[ \t]*"
        f"{re.escape(start_marker)}"
        r"\n.*?\n"
        r"[ \t]*"
        f"{re.escape(end_marker)}"
    )
    match = re.search(pattern, content, flags=re.DOTALL)
    if match is None:
        raise AssertionError(f"Provider block '{provider_name}' was not found.")
    return match.group(0)


def _load_module(*, module_path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Failed to load generated module from {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload
