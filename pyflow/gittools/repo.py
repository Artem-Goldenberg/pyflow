from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from pyflow.gittools.types import (
    GitCommandError,
    GitCommandResult,
    GitDiffResult,
    GitMergeState,
    GitStatusEntry,
    GitStatusResult,
    WorktreeInfo,
)


type DiffMode = Literal["patch", "name_status", "stat"]
type WorktreeInput = WorktreeInfo | str | Path


@dataclass(frozen=True, kw_only=True)
class GitRepo:
    """Lightweight typed wrapper around a Git repository and its worktrees."""

    repo_root: Path
    default_target: Path

    @staticmethod
    def open(path: str | Path) -> GitRepo:
        """Open the Git repository that contains ``path``."""
        candidate = Path(path).expanduser()
        target = candidate.parent if candidate.exists() and candidate.is_file() else candidate

        try:
            result = _run_git(
                cwd=target,
                args=("rev-parse", "--show-toplevel"),
            )
        except GitCommandError as exc:
            raise ValueError(f"{candidate} is not inside a Git repository.") from exc

        repo_root = Path(result.stdout.strip())
        default_target = target.resolve() if target.exists() else target
        return GitRepo(
            repo_root=repo_root.resolve(),
            default_target=default_target,
        )

    def create_worktree(
        self,
        *,
        worktrees_root: str | Path,
        run_id: str,
        task_id: str,
        start_point: str = "HEAD",
        branch_name: str | None = None,
    ) -> WorktreeInfo:
        """Create a new linked worktree on a fresh branch."""
        root = _resolve_worktrees_root(self.repo_root, worktrees_root)
        run_component = _sanitize_path_component(run_id)
        task_component = _sanitize_path_component(task_id)
        worktree_path = root / run_component / task_component

        if worktree_path.exists():
            raise FileExistsError(f"Worktree path already exists: {worktree_path}")

        branch = branch_name or _generate_branch_name(run_id=run_id, task_id=task_id)
        self._validate_branch_name(branch)

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run_git(
                cwd=self.repo_root,
                args=(
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(worktree_path),
                    start_point,
                ),
            )
        except GitCommandError as exc:
            stderr = exc.result.stderr
            if "already checked out at" in stderr:
                raise ValueError(stderr.strip()) from exc
            raise

        return self._require_worktree(worktree_path)

    def list_worktrees(self) -> Sequence[WorktreeInfo]:
        """List all linked worktrees for this repository."""
        result = _run_git(
            cwd=self.repo_root,
            args=("worktree", "list", "--porcelain", "-z"),
        )
        return _parse_worktree_list(result=result, repo_root=self.repo_root)

    def remove_worktree(
        self,
        worktree: WorktreeInput,
        *,
        force: bool = False,
    ) -> GitCommandResult:
        """Remove one linked worktree."""
        worktree_path = self._resolve_worktree_path(worktree)
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))
        return _run_git(cwd=self.repo_root, args=tuple(args))

    def prune_worktrees(
        self,
        *,
        dry_run: bool = False,
        expire: str | None = None,
    ) -> GitCommandResult:
        """Prune stale linked-worktree metadata."""
        args = ["worktree", "prune"]
        if dry_run:
            args.append("--dry-run")
        if expire is not None:
            args.extend(("--expire", expire))
        return _run_git(cwd=self.repo_root, args=tuple(args))

    def status(
        self,
        target: WorktreeInput | None = None,
    ) -> GitStatusResult:
        """Return parsed ``git status`` output for one repository/worktree."""
        cwd = self._resolve_target(target)
        result = _run_git(
            cwd=cwd,
            args=("status", "--porcelain=v2", "--branch", "-z"),
        )
        return _parse_status(result)

    def diff(
        self,
        *,
        left: str | None = None,
        right: str | None = None,
        merge_base: bool = False,
        mode: DiffMode = "patch",
        pathspec: Sequence[str] = (),
    ) -> GitDiffResult:
        """Return structured diff data plus raw text output."""
        if right is not None and left is None:
            raise ValueError("right cannot be provided without left.")
        if merge_base and left is None:
            raise ValueError("merge_base requires at least one reference.")

        args = ["diff"]
        if mode == "name_status":
            args.extend(("--name-status", "-z"))
        elif mode == "stat":
            args.append("--stat")

        if merge_base:
            args.append("--merge-base")
        if left is not None:
            args.append(left)
        if right is not None:
            args.append(right)
        if pathspec:
            args.append("--")
            args.extend(pathspec)

        result = _run_git(cwd=self.default_target, args=tuple(args))
        entries: tuple[tuple[str, str, str | None], ...] = ()
        if mode == "name_status":
            entries = _parse_diff_name_status(result.stdout_bytes)

        return GitDiffResult(
            command=result,
            mode=mode,
            text=result.stdout,
            name_status_entries=entries,
            left=left,
            right=right,
            merge_base=merge_base,
            pathspec=pathspec,
        )

    def merge_base(self, *refs: str) -> Sequence[str]:
        """Return all merge bases for the provided refs."""
        if len(refs) < 2:
            raise ValueError("merge_base requires at least two refs.")

        result = _run_git(
            cwd=self.repo_root,
            args=("merge-base", "--all", *refs),
        )
        return tuple(line for line in result.stdout.splitlines() if line)

    def start_merge(
        self,
        worktree: WorktreeInput,
        ref: str,
    ) -> GitMergeState:
        """Start a non-fast-forward merge and stop before creating a commit."""
        worktree_path = self._resolve_worktree_path(worktree)
        initial_status = self.status(target=worktree_path)
        if not initial_status.is_clean:
            raise RuntimeError(
                f"Merge worktree must be clean before starting a merge: {worktree_path}"
            )

        result = _run_git(
            cwd=worktree_path,
            args=("merge", "--no-ff", "--no-commit", ref),
            ok_returncodes=(0, 1),
        )
        merge_state = self._collect_merge_state(
            worktree_path=worktree_path,
            command=result,
            target_ref=ref,
        )
        if result.returncode != 0 and not merge_state.merge_in_progress:
            raise GitCommandError(result)
        return merge_state

    def finish_merge(
        self,
        worktree: WorktreeInput,
        *,
        message: str | None = None,
    ) -> GitMergeState:
        """Finalize an in-progress merge after conflicts are resolved."""
        worktree_path = self._resolve_worktree_path(worktree)
        merge_head = _rev_parse_optional(worktree_path, "MERGE_HEAD")
        if merge_head is None:
            raise RuntimeError(f"No merge is in progress in {worktree_path}.")

        status = self.status(target=worktree_path)
        if status.conflict_paths:
            conflicts = ", ".join(status.conflict_paths)
            raise RuntimeError(f"Cannot finish merge with unresolved conflicts: {conflicts}")

        args = ["commit"]
        if message is None:
            args.append("--no-edit")
        else:
            args.extend(("-m", message))
        result = _run_git(cwd=worktree_path, args=tuple(args))
        return self._collect_merge_state(
            worktree_path=worktree_path,
            command=result,
            target_ref=None,
        )

    def abort_merge(
        self,
        worktree: WorktreeInput,
    ) -> GitCommandResult:
        """Abort the in-progress merge in the given worktree."""
        worktree_path = self._resolve_worktree_path(worktree)
        return _run_git(cwd=worktree_path, args=("merge", "--abort"))

    def _validate_branch_name(self, branch_name: str) -> None:
        try:
            _run_git(
                cwd=self.repo_root,
                args=("check-ref-format", "--branch", branch_name),
            )
        except GitCommandError as exc:
            raise ValueError(f"Invalid branch name: {branch_name}") from exc

    def _require_worktree(self, path: Path) -> WorktreeInfo:
        normalized_path = _normalize_path(path)
        for worktree in self.list_worktrees():
            if _normalize_path(worktree.path) == normalized_path:
                return worktree
        raise RuntimeError(
            f"Git created worktree at {normalized_path}, but it was not listed."
        )

    def _resolve_target(self, target: WorktreeInput | None) -> Path:
        if target is None:
            return self.default_target
        return self._resolve_worktree_path(target)

    def _resolve_worktree_path(self, worktree: WorktreeInput) -> Path:
        if isinstance(worktree, WorktreeInfo):
            return worktree.path
        return Path(worktree).expanduser()

    def _collect_merge_state(
        self,
        *,
        worktree_path: Path,
        command: GitCommandResult,
        target_ref: str | None,
    ) -> GitMergeState:
        status = self.status(target=worktree_path)
        merge_head = _rev_parse_optional(worktree_path, "MERGE_HEAD")
        auto_merge_ref = _rev_parse_optional(worktree_path, "AUTO_MERGE")
        return GitMergeState(
            worktree=worktree_path,
            command=command,
            status=status,
            target_ref=target_ref,
            merge_head=merge_head,
            auto_merge_ref=auto_merge_ref,
            merge_in_progress=merge_head is not None,
        )


def _run_git(
    *,
    cwd: Path,
    args: Sequence[str],
    ok_returncodes: Sequence[int] = (0,),
) -> GitCommandResult:
    command = (
        "git",
        "--no-pager",
        "-c",
        "color.ui=never",
        "-c",
        "core.pager=cat",
        "-C",
        str(cwd),
        *args,
    )
    env = {
        **os.environ,
        "GIT_PAGER": "cat",
        "LANG": "C",
        "LC_ALL": "C",
    }
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=env,
    )
    result = GitCommandResult(
        args=command,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=_decode_git_output(completed.stdout),
        stderr=_decode_git_output(completed.stderr),
        stdout_bytes=completed.stdout,
        stderr_bytes=completed.stderr,
    )
    if completed.returncode not in ok_returncodes:
        raise GitCommandError(result)
    return result


def _parse_worktree_list(
    *,
    result: GitCommandResult,
    repo_root: Path,
) -> Sequence[WorktreeInfo]:
    blocks: list[list[str]] = []
    current: list[str] = []

    for token in _split_nul_records(result.stdout_bytes):
        if token.startswith("worktree "):
            if current:
                blocks.append(current)
            current = [token]
            continue
        current.append(token)

    if current:
        blocks.append(current)

    return tuple(_parse_worktree_block(block=block, repo_root=repo_root) for block in blocks)


def _parse_worktree_block(
    *,
    block: Sequence[str],
    repo_root: Path,
) -> WorktreeInfo:
    path: Path | None = None
    head_oid: str | None = None
    branch: str | None = None
    detached = False
    locked = False
    lock_reason: str | None = None
    prunable = False
    prunable_reason: str | None = None

    for line in block:
        if line.startswith("worktree "):
            path = _normalize_path(Path(line.removeprefix("worktree ")))
            continue
        if line.startswith("HEAD "):
            head_oid = line.removeprefix("HEAD ")
            continue
        if line.startswith("branch "):
            branch = line.removeprefix("branch ")
            continue
        if line == "detached":
            detached = True
            continue
        if line == "locked":
            locked = True
            continue
        if line.startswith("locked "):
            locked = True
            lock_reason = line.removeprefix("locked ")
            continue
        if line == "prunable":
            prunable = True
            continue
        if line.startswith("prunable "):
            prunable = True
            prunable_reason = line.removeprefix("prunable ")

    if path is None or head_oid is None:
        raise RuntimeError("Unable to parse git worktree list output.")

    return WorktreeInfo(
        repo_root=repo_root,
        path=path,
        branch=branch,
        head_oid=head_oid,
        detached=detached,
        locked=locked,
        lock_reason=lock_reason,
        prunable=prunable,
        prunable_reason=prunable_reason,
        is_main=path == repo_root,
    )


def _parse_status(result: GitCommandResult) -> GitStatusResult:
    tokens = _split_nul_records(result.stdout_bytes)
    entries: list[GitStatusEntry] = []
    branch_oid: str | None = None
    branch_head: str | None = None
    branch_upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    detached = False

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("# "):
            key, _, value = token[2:].partition(" ")
            if key == "branch.oid":
                branch_oid = None if value == "(initial)" else value
            elif key == "branch.head":
                detached = value == "(detached)"
                branch_head = None if detached else value
            elif key == "branch.upstream":
                branch_upstream = value
            elif key == "branch.ab":
                ahead, behind = _parse_branch_ahead_behind(value)
            index += 1
            continue

        if token.startswith("1 "):
            entries.append(_parse_ordinary_status_entry(token))
            index += 1
            continue
        if token.startswith("2 "):
            if index + 1 >= len(tokens):
                raise RuntimeError("Malformed git status rename entry.")
            entries.append(_parse_renamed_status_entry(token, tokens[index + 1]))
            index += 2
            continue
        if token.startswith("u "):
            entries.append(_parse_unmerged_status_entry(token))
            index += 1
            continue
        if token.startswith("? "):
            entries.append(
                GitStatusEntry(
                    kind="untracked",
                    path=token[2:],
                )
            )
            index += 1
            continue
        if token.startswith("! "):
            entries.append(
                GitStatusEntry(
                    kind="ignored",
                    path=token[2:],
                )
            )
            index += 1
            continue
        raise RuntimeError(f"Unsupported git status token: {token!r}")

    return GitStatusResult(
        command=result,
        entries=entries,
        branch_oid=branch_oid,
        branch_head=branch_head,
        branch_upstream=branch_upstream,
        ahead=ahead,
        behind=behind,
        detached=detached,
    )


def _parse_ordinary_status_entry(token: str) -> GitStatusEntry:
    parts = token.split(" ", 8)
    if len(parts) != 9:
        raise RuntimeError(f"Malformed ordinary git status entry: {token!r}")
    _, xy, submodule_state, head_mode, index_mode, worktree_mode, head_oid, index_oid, path = (
        parts
    )
    staged_status, unstaged_status = xy[0], xy[1]
    return GitStatusEntry(
        kind="ordinary",
        path=path,
        status_code=xy,
        staged_status=staged_status,
        unstaged_status=unstaged_status,
        submodule_state=submodule_state,
        head_mode=head_mode,
        index_mode=index_mode,
        worktree_mode=worktree_mode,
        head_oid=head_oid,
        index_oid=index_oid,
    )


def _parse_renamed_status_entry(token: str, orig_path: str) -> GitStatusEntry:
    parts = token.split(" ", 9)
    if len(parts) != 10:
        raise RuntimeError(f"Malformed renamed git status entry: {token!r}")
    (
        _,
        xy,
        submodule_state,
        head_mode,
        index_mode,
        worktree_mode,
        head_oid,
        index_oid,
        score,
        path,
    ) = parts
    staged_status, unstaged_status = xy[0], xy[1]
    kind: Literal["renamed", "copied"] = "renamed" if score.startswith("R") else "copied"
    return GitStatusEntry(
        kind=kind,
        path=path,
        orig_path=orig_path,
        status_code=xy,
        staged_status=staged_status,
        unstaged_status=unstaged_status,
        submodule_state=submodule_state,
        head_mode=head_mode,
        index_mode=index_mode,
        worktree_mode=worktree_mode,
        head_oid=head_oid,
        index_oid=index_oid,
        rename_or_copy_score=score,
    )


def _parse_unmerged_status_entry(token: str) -> GitStatusEntry:
    parts = token.split(" ", 10)
    if len(parts) != 11:
        raise RuntimeError(f"Malformed unmerged git status entry: {token!r}")
    (
        _,
        xy,
        submodule_state,
        stage1_mode,
        stage2_mode,
        stage3_mode,
        worktree_mode,
        stage1_oid,
        stage2_oid,
        stage3_oid,
        path,
    ) = parts
    staged_status, unstaged_status = xy[0], xy[1]
    return GitStatusEntry(
        kind="unmerged",
        path=path,
        status_code=xy,
        staged_status=staged_status,
        unstaged_status=unstaged_status,
        submodule_state=submodule_state,
        worktree_mode=worktree_mode,
        stage1_mode=stage1_mode,
        stage2_mode=stage2_mode,
        stage3_mode=stage3_mode,
        stage1_oid=stage1_oid,
        stage2_oid=stage2_oid,
        stage3_oid=stage3_oid,
    )


def _parse_branch_ahead_behind(value: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"\+(?P<ahead>\d+) -(?P<behind>\d+)", value)
    if match is None:
        return None, None
    return int(match.group("ahead")), int(match.group("behind"))


def _parse_diff_name_status(data: bytes) -> tuple[tuple[str, str, str | None], ...]:
    tokens = _split_nul_records(data)
    entries: list[tuple[str, str, str | None]] = []

    index = 0
    while index < len(tokens):
        status = tokens[index]
        if status.startswith(("R", "C")):
            if index + 2 >= len(tokens):
                raise RuntimeError("Malformed git diff --name-status output.")
            old_path = tokens[index + 1]
            new_path = tokens[index + 2]
            entries.append((status, new_path, old_path))
            index += 3
            continue
        if index + 1 >= len(tokens):
            raise RuntimeError("Malformed git diff --name-status output.")
        entries.append((status, tokens[index + 1], None))
        index += 2

    return tuple(entries)


def _split_nul_records(data: bytes) -> list[str]:
    text = _decode_git_output(data)
    records = text.split("\0")
    if records and records[-1] == "":
        records.pop()
    return records


def _decode_git_output(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")


def _rev_parse_optional(cwd: Path, ref: str) -> str | None:
    result = _run_git(
        cwd=cwd,
        args=("rev-parse", "-q", "--verify", ref),
        ok_returncodes=(0, 1),
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _resolve_worktrees_root(repo_root: Path, worktrees_root: str | Path) -> Path:
    root = Path(worktrees_root).expanduser()
    if not root.is_absolute():
        root = repo_root / root
    return _normalize_path(root)


def _normalize_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _generate_branch_name(*, run_id: str, task_id: str) -> str:
    run_component = _sanitize_branch_component(run_id)
    task_component = _sanitize_branch_component(task_id)
    branch_name = f"pyflow/{run_component}/{task_component}"
    if not branch_name:
        raise ValueError("Generated branch name is empty.")
    return branch_name


def _sanitize_branch_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    sanitized = re.sub(r"\.{2,}", ".", sanitized)
    if sanitized.endswith(".lock"):
        sanitized = f"{sanitized[:-5]}-lock"
    if sanitized in {"", "@", "HEAD"}:
        raise ValueError(f"Cannot derive a valid branch component from {value!r}.")
    return sanitized


def _sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    if sanitized in {"", ".", ".."}:
        raise ValueError(f"Cannot derive a valid path component from {value!r}.")
    return sanitized
