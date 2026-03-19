from __future__ import annotations

import logging

import pytest

from pyflow import Agent, TestModel
from pyflow.notebook_visualizer import NotebookConversationVisualizer
from pyflow.runtime_logging import (
    apply_default_jupyter_backend_log_policy,
    hide_backend_logs,
    set_backend_log_level,
    show_backend_logs,
)


def test_apply_default_jupyter_backend_log_policy_sets_warning_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger_map = _install_test_backend_loggers(monkeypatch)
    monkeypatch.setattr("pyflow.runtime_logging._explicit_backend_log_level", None)

    apply_default_jupyter_backend_log_policy()

    assert {name: logger.level for name, logger in logger_map.items()} == {
        "openhands": logging.WARNING,
        "litellm": logging.WARNING,
        "LiteLLM": logging.WARNING,
        "openai": logging.WARNING,
    }


def test_explicit_backend_log_level_prevents_default_notebook_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger_map = _install_test_backend_loggers(monkeypatch)
    monkeypatch.setattr("pyflow.runtime_logging._explicit_backend_log_level", None)

    set_backend_log_level("ERROR")
    apply_default_jupyter_backend_log_policy()

    assert {name: logger.level for name, logger in logger_map.items()} == {
        "openhands": logging.ERROR,
        "litellm": logging.ERROR,
        "LiteLLM": logging.ERROR,
        "openai": logging.ERROR,
    }


def test_hide_and_show_backend_logs_adjust_backend_logger_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger_map = _install_test_backend_loggers(monkeypatch)
    monkeypatch.setattr("pyflow.runtime_logging._explicit_backend_log_level", None)

    hide_backend_logs()
    show_backend_logs("INFO")

    assert {name: logger.level for name, logger in logger_map.items()} == {
        "openhands": logging.INFO,
        "litellm": logging.INFO,
        "LiteLLM": logging.INFO,
        "openai": logging.INFO,
    }


def test_agent_run_uses_environment_visualizer_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    fake_conversation = _FakeConversation()

    def visualizer_factory() -> NotebookConversationVisualizer:
        nonlocal calls
        calls += 1
        return NotebookConversationVisualizer()

    def conversation_factory(**kwargs: object) -> _FakeConversation:
        del kwargs
        return fake_conversation

    monkeypatch.setattr(
        "pyflow.agent.conversation_visualizer_for_environment",
        visualizer_factory,
    )
    monkeypatch.setattr("pyflow.agent.Conversation", conversation_factory)
    monkeypatch.setattr("pyflow.agent.sync_interactive_session", lambda session: None)

    _ = "Inspect notebook log noise." >> Agent(
        model=TestModel(scripted_responses=(), name="unused"),
        tools=(),
    )

    assert calls == 1


class _FakeConversation:
    def send_message(self, message: str) -> None:
        del message

    def run(self) -> None:
        return None


def _install_test_backend_loggers(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, logging.Logger]:
    logger_names = (
        "pyflow.tests.backend.openhands",
        "pyflow.tests.backend.litellm",
        "pyflow.tests.backend.LiteLLM",
        "pyflow.tests.backend.openai",
    )
    monkeypatch.setattr("pyflow.runtime_logging._BACKEND_LOGGER_NAMES", logger_names)

    logger_map: dict[str, logging.Logger] = {}
    for name in logger_names:
        logger = logging.getLogger(name)
        logger.setLevel(logging.NOTSET)
        logger_map[name.rsplit(".", maxsplit=1)[-1]] = logger
    return logger_map
