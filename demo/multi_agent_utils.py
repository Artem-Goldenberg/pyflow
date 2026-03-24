from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pyflow.gittools import GitRepo, WorktreeInfo


@dataclass(frozen=True, kw_only=True)
class TaskboardDemo:
    repo_path: Path
    repo: GitRepo
    worktrees_root: Path
    priority_branch: str
    due_date_branch: str
    priority_worktree: WorktreeInfo
    due_date_worktree: WorktreeInfo


def git(
    cwd: Path,
    *args: str,
    ok_returncodes: Sequence[int] = (0,),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", "--no-pager", "-C", str(cwd), *args),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in ok_returncodes:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}:\n{stderr}")
    return completed


def run_command(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    chunks = [f"$ {' '.join(args)}", f"returncode={completed.returncode}"]
    if completed.stdout.strip():
        chunks.append("stdout:")
        chunks.append(completed.stdout.rstrip())
    if completed.stderr.strip():
        chunks.append("stderr:")
        chunks.append(completed.stderr.rstrip())
    return "\n".join(chunks)


def format_name_status_diff(entries: Sequence[tuple[str, str, str | None]]) -> str:
    if not entries:
        return "(no changed files)"
    lines: list[str] = []
    for status, path, original_path in entries:
        if original_path is None:
            lines.append(f"{status} {path}")
        else:
            lines.append(f"{status} {original_path} -> {path}")
    return "\n".join(lines)


def materialize_demo_repo(
    *,
    source_project_root: Path,
    destination: Path,
) -> Path:
    shutil.copytree(
        source_project_root,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".DS_Store",
            "*.ipynb",
        ),
    )
    git(destination, "init", "-b", "main")
    git(destination, "config", "user.name", "Pyflow Demo")
    git(destination, "config", "user.email", "demo@example.com")
    git(destination, "add", ".")
    git(destination, "commit", "-m", "Initial taskboard demo")
    return destination


def prepare_taskboard_demo(
    *,
    repo_root: Path,
    run_id: str,
) -> TaskboardDemo:
    resolved_repo_root = repo_root.expanduser().resolve()
    source_project_root = resolved_repo_root / "taskboard_demo"
    demo_parent = Path(tempfile.mkdtemp(prefix="pyflow-taskboard-nb-")).resolve()
    demo_repo_path = materialize_demo_repo(
        source_project_root=source_project_root,
        destination=demo_parent / "taskboard-demo",
    )
    demo_repo = GitRepo.open(demo_repo_path)
    worktrees_root = (demo_repo_path.parent / "taskboard-demo-worktrees").resolve()

    priority_branch = f"demo/{run_id}/priority"
    due_date_branch = f"demo/{run_id}/due-date"

    priority_worktree = demo_repo.create_worktree(
        worktrees_root=worktrees_root,
        run_id=run_id,
        task_id="priority",
        start_point="main",
        branch_name=priority_branch,
    )
    due_date_worktree = demo_repo.create_worktree(
        worktrees_root=worktrees_root,
        run_id=run_id,
        task_id="due-date",
        start_point="main",
        branch_name=due_date_branch,
    )

    return TaskboardDemo(
        repo_path=demo_repo_path,
        repo=demo_repo,
        worktrees_root=worktrees_root,
        priority_branch=priority_branch,
        due_date_branch=due_date_branch,
        priority_worktree=priority_worktree,
        due_date_worktree=due_date_worktree,
    )
