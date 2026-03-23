from __future__ import annotations

from pathlib import Path

from taskboard.cli import main
from taskboard.storage import load_tasks


def test_list_reports_empty_board(tmp_path: Path, capsys: object) -> None:
    db_path = tmp_path / "taskboard.json"

    exit_code = main(["--db", str(db_path), "list"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "No tasks."


def test_add_and_list_tasks(tmp_path: Path, capsys: object) -> None:
    db_path = tmp_path / "taskboard.json"

    add_exit_code = main(["--db", str(db_path), "add", "Buy milk"])
    add_output = capsys.readouterr().out.strip()
    list_exit_code = main(["--db", str(db_path), "list"])
    list_output = capsys.readouterr().out.strip().splitlines()

    assert add_exit_code == 0
    assert add_output == "Added task 1: Buy milk"
    assert list_exit_code == 0
    assert list_output == ["1. [ ] Buy milk"]


def test_done_marks_task_complete(tmp_path: Path, capsys: object) -> None:
    db_path = tmp_path / "taskboard.json"
    main(["--db", str(db_path), "add", "Ship demo"])
    capsys.readouterr()

    exit_code = main(["--db", str(db_path), "done", "1"])
    output = capsys.readouterr().out.strip()
    tasks = load_tasks(db_path)

    assert exit_code == 0
    assert output == "Completed task 1."
    assert tasks[0].done is True


def test_done_returns_error_for_missing_task(tmp_path: Path, capsys: object) -> None:
    db_path = tmp_path / "taskboard.json"
    main(["--db", str(db_path), "add", "Ship demo"])
    capsys.readouterr()

    exit_code = main(["--db", str(db_path), "done", "99"])
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.err.strip() == "Task 99 not found."
