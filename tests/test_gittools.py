from __future__ import annotations

import os
import subprocess

from pathlib import Path

import pytest

from pyflow.gittools import GitRepo


def test_git_repo_open_resolves_repo_root_from_nested_path(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path)
    nested_path = repo_path / "src"
    nested_path.mkdir()

    repo = GitRepo.open(nested_path)

    assert repo.repo_root == repo_path
    assert repo.default_target == nested_path


def test_create_worktree_generates_branch_and_lists_worktrees(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path)
    repo = GitRepo.open(repo_path)

    worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run 1",
        task_id="task/a",
    )

    assert worktree.path == tmp_path / "trees" / "run-1" / "task-a"
    assert worktree.branch == "refs/heads/pyflow/run-1/task-a"
    assert worktree.path.exists()
    assert worktree.head_oid == _git_output(worktree.path, "rev-parse", "HEAD").strip()

    listed_paths = {item.path for item in repo.list_worktrees()}
    assert repo_path in listed_paths
    assert worktree.path in listed_paths


def test_create_worktree_accepts_explicit_branch_name(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path)
    repo = GitRepo.open(repo_path)

    worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run",
        task_id="explicit",
        branch_name="feature/agent-a",
    )

    assert worktree.branch == "refs/heads/feature/agent-a"


def test_create_worktree_resolves_symlinked_worktrees_root(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path)
    repo = GitRepo.open(repo_path)

    target_root = tmp_path / "trees-target"
    target_root.mkdir()
    symlink_root = tmp_path / "trees-link"
    try:
        symlink_root.symlink_to(target_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this environment: {exc}")

    worktree = repo.create_worktree(
        worktrees_root=symlink_root,
        run_id="run",
        task_id="through-link",
    )

    assert worktree.path == target_root / "run" / "through-link"
    assert worktree.path.exists()
    assert worktree.path.parent.parent == target_root

    listed_paths = {item.path for item in repo.list_worktrees()}
    assert worktree.path in listed_paths


def test_remove_worktree_deletes_linked_tree(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path)
    repo = GitRepo.open(repo_path)
    worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run",
        task_id="cleanup",
    )

    repo.remove_worktree(worktree)

    assert not worktree.path.exists()


def test_status_parses_modified_renamed_and_untracked_entries(tmp_path: Path) -> None:
    repo_path = _init_repo(
        tmp_path,
        files={
            "keep.txt": "base\n",
            "rename.txt": "rename me\n",
        },
    )
    repo = GitRepo.open(repo_path)

    _append_file(repo_path / "keep.txt", "changed\n")
    _git(repo_path, "mv", "rename.txt", "renamed.txt")
    _write_file(repo_path / "new.txt", "new\n")

    status = repo.status()
    entries_by_path = {entry.path: entry for entry in status.entries}

    assert status.branch_head == "main"
    assert entries_by_path["keep.txt"].kind == "ordinary"
    assert entries_by_path["keep.txt"].status_code == ".M"
    assert entries_by_path["renamed.txt"].kind == "renamed"
    assert entries_by_path["renamed.txt"].orig_path == "rename.txt"
    assert entries_by_path["new.txt"].kind == "untracked"


def test_diff_supports_merge_base_name_status_patch_and_stat_modes(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo(
        tmp_path,
        files={"shared.txt": "base\n"},
    )
    repo = GitRepo.open(repo_path)

    _git(repo_path, "checkout", "-b", "feature")
    _append_file(repo_path / "shared.txt", "feature\n")
    _git(repo_path, "commit", "-am", "feature change")
    _git(repo_path, "checkout", "main")
    _append_file(repo_path / "shared.txt", "main\n")
    _git(repo_path, "commit", "-am", "main change")

    name_status = repo.diff(
        left="main",
        right="feature",
        merge_base=True,
        mode="name_status",
    )
    patch = repo.diff(left="main", right="feature", mode="patch")
    stat = repo.diff(left="main", right="feature", mode="stat")

    assert name_status.name_status_entries == (("M", "shared.txt", None),)
    assert "shared.txt" in patch.text
    assert "shared.txt" in stat.text


def test_start_merge_requires_clean_worktree(tmp_path: Path) -> None:
    repo_path = _init_repo(
        tmp_path,
        files={"shared.txt": "base\n"},
    )
    repo = GitRepo.open(repo_path)

    _git(repo_path, "checkout", "-b", "feature")
    _append_file(repo_path / "shared.txt", "feature\n")
    _git(repo_path, "commit", "-am", "feature change")
    _git(repo_path, "checkout", "main")

    merge_worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run",
        task_id="dirty",
        start_point="main",
        branch_name="merge/dirty",
    )
    _append_file(merge_worktree.path / "shared.txt", "dirty\n")

    with pytest.raises(RuntimeError, match="clean"):
        repo.start_merge(merge_worktree, "feature")


def test_start_merge_reports_conflicts_and_abort_restores_state(tmp_path: Path) -> None:
    repo_path = _init_repo(
        tmp_path,
        files={"conflict.txt": "base\n"},
    )
    repo = GitRepo.open(repo_path)

    _git(repo_path, "checkout", "-b", "agent/one")
    _write_file(repo_path / "conflict.txt", "one\n")
    _git(repo_path, "commit", "-am", "agent one")
    _git(repo_path, "checkout", "main")

    _git(repo_path, "checkout", "-b", "agent/two")
    _write_file(repo_path / "conflict.txt", "two\n")
    _git(repo_path, "commit", "-am", "agent two")
    _git(repo_path, "checkout", "main")

    merge_worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run",
        task_id="merge-conflict",
        start_point="agent/one",
        branch_name="merge/conflict",
    )

    merge_state = repo.start_merge(merge_worktree, "agent/two")

    assert merge_state.merge_in_progress is True
    assert merge_state.conflict_paths == ("conflict.txt",)
    assert merge_state.auto_merge_ref is not None
    assert "CONFLICT" in merge_state.command.stdout

    repo.abort_merge(merge_worktree)

    status = repo.status(target=merge_worktree)
    assert status.is_clean is True
    assert (merge_worktree.path / "conflict.txt").read_text(encoding="utf-8") == "one\n"


def test_clean_merge_can_be_finished_non_interactively(tmp_path: Path) -> None:
    repo_path = _init_repo(
        tmp_path,
        files={"base.txt": "base\n"},
    )
    repo = GitRepo.open(repo_path)

    _git(repo_path, "checkout", "-b", "agent/one")
    _write_file(repo_path / "one.txt", "one\n")
    _git(repo_path, "add", "one.txt")
    _git(repo_path, "commit", "-m", "agent one")
    _git(repo_path, "checkout", "main")

    _git(repo_path, "checkout", "-b", "agent/two")
    _write_file(repo_path / "two.txt", "two\n")
    _git(repo_path, "add", "two.txt")
    _git(repo_path, "commit", "-m", "agent two")
    _git(repo_path, "checkout", "main")

    merge_worktree = repo.create_worktree(
        worktrees_root=tmp_path / "trees",
        run_id="run",
        task_id="merge-clean",
        start_point="agent/one",
        branch_name="merge/clean",
    )

    started = repo.start_merge(merge_worktree, "agent/two")
    finished = repo.finish_merge(merge_worktree)

    assert started.merge_in_progress is True
    assert started.conflict_paths == ()
    assert finished.merge_in_progress is False
    assert finished.status.is_clean is True
    assert len(_git_output(merge_worktree.path, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3


def _init_repo(
    tmp_path: Path,
    *,
    files: dict[str, str] | None = None,
) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git(repo_path, "init", "-b", "main")
    _git(repo_path, "config", "user.name", "Pyflow Tests")
    _git(repo_path, "config", "user.email", "tests@example.com")

    initial_files = files or {"README.md": "base\n"}
    for relative_path, content in initial_files.items():
        _write_file(repo_path / relative_path, content)
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-m", "initial")
    return repo_path


def _git(
    cwd: Path,
    *args: str,
    ok_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    env = {
        **os.environ,
        "GIT_PAGER": "cat",
        "LANG": "C",
        "LC_ALL": "C",
    }
    completed = subprocess.run(
        ("git", "--no-pager", "-c", "color.ui=never", "-C", str(cwd), *args),
        check=False,
        capture_output=True,
        env=env,
    )
    if completed.returncode not in ok_returncodes:
        raise AssertionError(
            f"git {' '.join(args)} failed in {cwd}: {completed.stderr.decode('utf-8', errors='replace')}"
        )
    return completed


def _git_output(cwd: Path, *args: str) -> str:
    return _git(cwd, *args).stdout.decode("utf-8", errors="surrogateescape")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append_file(path: Path, content: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + content, encoding="utf-8")
