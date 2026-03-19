from __future__ import annotations

import logging


_BACKEND_LOGGER_NAMES = (
    "openhands",
    "litellm",
    "LiteLLM",
    "openai",
)
_DEFAULT_NOTEBOOK_BACKEND_LEVEL = logging.WARNING
_explicit_backend_log_level: int | None = None


def set_backend_log_level(level: int | str) -> None:
    """Set the textual log level for backend runtime loggers."""
    resolved_level = _resolve_log_level(level)

    global _explicit_backend_log_level
    _explicit_backend_log_level = resolved_level
    _apply_backend_log_level(resolved_level)


def hide_backend_logs() -> None:
    """Hide backend informational logs while preserving warnings and errors."""
    set_backend_log_level(logging.WARNING)


def show_backend_logs(level: int | str = logging.INFO) -> None:
    """Show backend logs at the requested verbosity."""
    set_backend_log_level(level)


def apply_default_jupyter_backend_log_policy() -> None:
    """Keep backend logs quiet in notebooks unless the user overrides them."""
    if _explicit_backend_log_level is not None:
        return
    _apply_backend_log_level(_DEFAULT_NOTEBOOK_BACKEND_LEVEL)


def _apply_backend_log_level(level: int) -> None:
    for logger_name in _BACKEND_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(level)


def _resolve_log_level(level: int | str) -> int:
    if isinstance(level, int):
        return level

    normalized = level.strip().upper()
    resolved = logging.getLevelNamesMapping().get(normalized)
    if resolved is None:
        raise ValueError(f"Unknown log level: {level!r}")
    return resolved
