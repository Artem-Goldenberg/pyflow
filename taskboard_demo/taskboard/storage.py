from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Sequence

from taskboard.models import Task


def load_tasks(path: Path) -> list[Task]:
    """Load tasks from a JSON file, returning an empty list when it does not exist."""
    if not path.exists():
        return []

    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Task database must contain a JSON list.")
    return [task_from_record(record) for record in records]


def save_tasks(path: Path, tasks: Sequence[Task]) -> None:
    """Persist tasks to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [task_to_record(task) for task in tasks]
    path.write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def next_task_id(tasks: Sequence[Task]) -> int:
    """Return the next available task identifier."""
    if not tasks:
        return 1
    return max(task.id for task in tasks) + 1


def task_from_record(record: Any) -> Task:
    """Build a task from a JSON object."""
    if not isinstance(record, dict):
        raise ValueError("Task record must be a JSON object.")

    created_at = record.get("created_at")
    task_data: dict[str, object] = {
        "id": int(record["id"]),
        "title": str(record["title"]),
        "done": bool(record.get("done", False)),
    }
    if created_at is not None:
        task_data["created_at"] = str(created_at)
    return Task(**task_data)


def task_to_record(task: Task) -> dict[str, object]:
    """Serialize a task into a JSON-ready dictionary."""
    return {
        "id": task.id,
        "title": task.title,
        "done": task.done,
        "created_at": task.created_at,
    }
