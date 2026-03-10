from __future__ import annotations

import pytest


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
