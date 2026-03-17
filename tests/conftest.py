from __future__ import annotations

import os
import sys

import dotenv
import dotenv.main
import pytest
from typing import Any, Callable, cast


def _disable_telemetry_for_tests() -> None:
    # OpenHands checks dotenv at import-time to decide observability enablement.
    def _empty_dotenv_values(*args: Any, **kwargs: Any) -> dict[str, str | None]:
        return {}

    def _no_dotenv_path(*args: Any, **kwargs: Any) -> str:
        return ""

    patched = cast(Callable[..., dict[str, str | None]], _empty_dotenv_values)
    dotenv.dotenv_values = patched
    dotenv.main.dotenv_values = patched
    dotenv.find_dotenv = cast(Callable[..., str], _no_dotenv_path)
    dotenv.main.find_dotenv = cast(Callable[..., str], _no_dotenv_path)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    # LiteLLM reads this at import-time; force local backup to skip network fetches.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

    for key in (
        "LMNR_PROJECT_API_KEY",
        "OTEL_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        os.environ.pop(key, None)


if os.getenv("PYFLOW_DISABLE_TEST_TELEMETRY", "1") == "1" and (
    "pytest" in os.path.basename(sys.argv[0]) or "PYTEST_CURRENT_TEST" in os.environ
):
    _disable_telemetry_for_tests()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--regen",
        action="store_true",
        default=False,
        help="Regenerate snapshot fixtures.",
    )


@pytest.fixture
def snapshot_regen(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--regen"))
