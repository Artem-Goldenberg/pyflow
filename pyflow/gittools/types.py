from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence


@dataclass(frozen=True, kw_only=True)
class GitCommandResult:
    """Captured result of one Git CLI invocation."""

    args: Sequence[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    stdout_bytes: bytes = field(repr=False)
    stderr_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "cwd", Path(self.cwd))


class GitCommandError(RuntimeError):
    """Raised when a Git command exits with an unexpected status code."""

    def __init__(
        self,
        result: GitCommandResult,
        message: str | None = None,
    ) -> None:
        self.result = result
        super().__init__(message or _default_git_error_message(result))


@dataclass(frozen=True, kw_only=True)
class WorktreeInfo:
    """Structured metadata for one linked worktree."""

    repo_root: Path
    path: Path
    branch: str | None
    head_oid: str
    detached: bool = False
    locked: bool = False
    lock_reason: str | None = None
    prunable: bool = False
    prunable_reason: str | None = None
    is_main: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "repo_root", Path(self.repo_root))
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True, kw_only=True)
class GitStatusEntry:
    """One parsed entry from ``git status --porcelain=v2``."""

    kind: Literal["ordinary", "renamed", "copied", "untracked", "ignored", "unmerged"]
    path: str
    orig_path: str | None = None
    status_code: str | None = None
    staged_status: str | None = None
    unstaged_status: str | None = None
    submodule_state: str | None = None
    head_mode: str | None = None
    index_mode: str | None = None
    worktree_mode: str | None = None
    head_oid: str | None = None
    index_oid: str | None = None
    rename_or_copy_score: str | None = None
    stage1_mode: str | None = None
    stage2_mode: str | None = None
    stage3_mode: str | None = None
    stage1_oid: str | None = None
    stage2_oid: str | None = None
    stage3_oid: str | None = None


@dataclass(frozen=True, kw_only=True)
class GitStatusResult:
    """Parsed status plus raw command output for one repository/worktree."""

    command: GitCommandResult
    entries: Sequence[GitStatusEntry]
    branch_oid: str | None = None
    branch_head: str | None = None
    branch_upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    detached: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))

    @property
    def is_clean(self) -> bool:
        """Whether the worktree has no reported changes."""
        return not self.entries

    @property
    def conflict_paths(self) -> Sequence[str]:
        """Paths currently in an unmerged state."""
        return tuple(entry.path for entry in self.entries if entry.kind == "unmerged")


@dataclass(frozen=True, kw_only=True)
class GitDiffResult:
    """Structured diff output with raw text preserved."""

    command: GitCommandResult
    mode: Literal["patch", "name_status", "stat"]
    text: str
    name_status_entries: Sequence[tuple[str, str, str | None]] = ()
    left: str | None = None
    right: str | None = None
    merge_base: bool = False
    pathspec: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name_status_entries", tuple(self.name_status_entries))
        object.__setattr__(self, "pathspec", tuple(self.pathspec))


@dataclass(frozen=True, kw_only=True)
class GitMergeState:
    """Merge state snapshot collected after merge-related commands."""

    worktree: Path
    command: GitCommandResult
    status: GitStatusResult
    target_ref: str | None = None
    merge_head: str | None = None
    auto_merge_ref: str | None = None
    merge_in_progress: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "worktree", Path(self.worktree))

    @property
    def conflict_paths(self) -> Sequence[str]:
        """Paths with unresolved merge conflicts."""
        return self.status.conflict_paths


def _default_git_error_message(result: GitCommandResult) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    command = " ".join(result.args)
    return f"Git command failed: {command}: {detail}"
