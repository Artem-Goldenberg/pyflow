from __future__ import annotations

import logging
from rich.logging import RichHandler


_BACKEND_LOGGER_NAMES = (
    "openhands",
    "litellm",
    "LiteLLM",
    "openai",
)
_DEFAULT_BACKEND_LEVEL = logging.WARNING
_DEFAULT_NOTEBOOK_BACKEND_LEVEL = logging.WARNING
_explicit_backend_log_level: int | None = None
_drop_empty_rich_log_filter: _DropEmptyRichLogFilter | None = None


class _DropEmptyRichLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info is not None or record.stack_info is not None:
            return True
        return bool(record.getMessage().strip())


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


def apply_default_backend_log_policy() -> None:
    """Keep backend logs quiet unless the user explicitly overrides them."""
    if _explicit_backend_log_level is not None:
        return
    _apply_backend_log_level(_DEFAULT_BACKEND_LEVEL)


def apply_default_jupyter_backend_log_policy() -> None:
    """Keep backend logs quiet in notebooks unless the user overrides them."""
    _install_drop_empty_rich_log_filter()
    if _DEFAULT_NOTEBOOK_BACKEND_LEVEL == _DEFAULT_BACKEND_LEVEL:
        apply_default_backend_log_policy()
        return
    if _explicit_backend_log_level is not None:
        return
    _apply_backend_log_level(_DEFAULT_NOTEBOOK_BACKEND_LEVEL)


def _apply_backend_log_level(level: int) -> None:
    for logger_name in _BACKEND_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(level)


def _install_drop_empty_rich_log_filter() -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if not isinstance(handler, RichHandler):
            continue
        if _has_drop_empty_filter(handler):
            continue
        handler.addFilter(_drop_empty_filter())


def _drop_empty_filter() -> _DropEmptyRichLogFilter:
    global _drop_empty_rich_log_filter
    if _drop_empty_rich_log_filter is None:
        _drop_empty_rich_log_filter = _DropEmptyRichLogFilter()
    return _drop_empty_rich_log_filter


def _has_drop_empty_filter(handler: logging.Handler) -> bool:
    return any(
        isinstance(filter_instance, _DropEmptyRichLogFilter)
        for filter_instance in handler.filters
    )


def _resolve_log_level(level: int | str) -> int:
    if isinstance(level, int):
        return level

    normalized = level.strip().upper()
    resolved = logging.getLevelNamesMapping().get(normalized)
    if resolved is None:
        raise ValueError(f"Unknown log level: {level!r}")
    return resolved
