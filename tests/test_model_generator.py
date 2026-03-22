from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from urllib import request

import pytest

import pyflow.model_generator as model_generator
from pyflow import AIModel


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

    assert "qwen_72b" in first_provider_block
    assert "qwen_16b" not in first_provider_block
    assert second_provider_block_after == second_provider_block_before


def test_generated_models_expose_nested_and_flat_lazy_aliases(
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
    flat_reference = generated.Models.qwen_16b
    provider_reference = generated.Models.qw.qwen_16b
    nested_reference = generated.Models.qw.qwen.small.b16

    assert flat_reference is provider_reference
    assert not isinstance(flat_reference, AIModel)

    explicit_model = flat_reference(api_key="manual-key")
    assert isinstance(explicit_model, AIModel)
    assert explicit_model.name == "qwen-16b"
    assert explicit_model.base_url == "https://provider.example/v1"
    assert explicit_model.api_key.get_secret_value() == "manual-key"

    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValueError, match="Missing API key"):
        _ = flat_reference()

    monkeypatch.setenv("API_KEY", "from-env")
    env_model = nested_reference()
    assert env_model.name == "qwen-small-16b"
    assert env_model.api_key.get_secret_value() == "from-env"


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
    assert captured["timeout"] == 12.5


def _extract_provider_block(*, content: str, provider_name: str) -> str:
    start_marker = f"# >>> PYFLOW_PROVIDER_MODELS_START: {provider_name}"
    end_marker = f"# <<< PYFLOW_PROVIDER_MODELS_END: {provider_name}"
    pattern = (
        f"{re.escape(start_marker)}"
        r"\n.*?\n"
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
