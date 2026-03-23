from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True, kw_only=True)
class Task:
    """One task in the taskboard JSON store."""

    id: int
    title: str
    done: bool = False
    created_at: str = field(default_factory=_timestamp)

    def mark_done(self) -> Task:
        """Return a copy of the task marked as done."""
        return Task(
            id=self.id,
            title=self.title,
            done=True,
            created_at=self.created_at,
        )


def sort_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Return tasks in display order."""
    return sorted(
        tasks,
        key=lambda task: (task.done, task.created_at, task.id),
    )
