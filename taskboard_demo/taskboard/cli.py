from __future__ import annotations

import argparse
import sys

from pathlib import Path
from typing import Sequence

from taskboard.models import Task, sort_tasks
from taskboard.storage import load_tasks, next_task_id, save_tasks


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="taskboard")
    parser.add_argument(
        "--db",
        default="taskboard.json",
        help="Path to the JSON task database.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a new task.")
    add_parser.add_argument("title", help="Task title.")

    subparsers.add_parser("list", help="List tasks.")

    done_parser = subparsers.add_parser("done", help="Mark a task as done.")
    done_parser.add_argument("task_id", type=int, help="Task identifier.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the taskboard CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    if args.command == "add":
        tasks = load_tasks(db_path)
        task = Task(
            id=next_task_id(tasks),
            title=args.title,
        )
        updated_tasks = [*tasks, task]
        save_tasks(db_path, updated_tasks)
        print(f"Added task {task.id}: {task.title}")
        return 0

    if args.command == "list":
        tasks = sort_tasks(load_tasks(db_path))
        if not tasks:
            print("No tasks.")
            return 0

        for task in tasks:
            print(render_task(task))
        return 0

    if args.command == "done":
        tasks = load_tasks(db_path)
        updated_tasks = [mark_task_done(task, args.task_id) for task in tasks]
        if updated_tasks == tasks:
            print(f"Task {args.task_id} not found.", file=sys.stderr)
            return 1
        save_tasks(db_path, updated_tasks)
        print(f"Completed task {args.task_id}.")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


def render_task(task: Task) -> str:
    """Render one task for terminal output."""
    marker = "x" if task.done else " "
    return f"{task.id}. [{marker}] {task.title}"


def mark_task_done(task: Task, task_id: int) -> Task:
    """Return either the original task or a completed copy."""
    if task.id != task_id:
        return task
    return task.mark_done()


if __name__ == "__main__":
    raise SystemExit(main())
