import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pyflow import ParallelFailure, Session


@dataclass(frozen=True, kw_only=True)
class BenchmarkCase:
    instance_id: str
    repo_dir: str
    base_commit: str
    problem: str
    tests: Sequence[str]


@dataclass(frozen=True, kw_only=True)
class PromptVariant:
    name: str
    extra_instructions: str | None = None


def markdown_table(rows: Sequence[dict[str, str]]) -> str:
    if not rows:
        return "_No rows._"

    headers = list(rows[0].keys())
    header_row = "| " + " | ".join(headers) + " |"
    separator_row = "| " + " | ".join("---" for _ in headers) + " |"
    body_rows = [
        "| "
        + " | ".join(row.get(header, "").replace("|", "\\|") for header in headers)
        + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator_row, *body_rows])


def reset_case_workspaces(
    workspace_root: Path,
    cases: Sequence[BenchmarkCase],
) -> None:
    for case in cases:
        case_dir = _case_dir(workspace_root, case)
        subprocess.run(
            ["git", "reset", "--hard", case.base_commit],
            cwd=case_dir,
            check=True,
        )
        subprocess.run(
            ["git", "clean", "-fd", "-e", ".venv"],
            cwd=case_dir,
            check=True,
        )


def save_run_artifacts(
    artifact_root: Path,
    label: str,
    cases: Sequence[BenchmarkCase],
    results: Sequence[Session | ParallelFailure[BenchmarkCase]],
) -> None:
    output_dir = artifact_root / label
    output_dir.mkdir(parents=True, exist_ok=True)

    for case, result in zip(cases, results, strict=True):
        if isinstance(result, ParallelFailure):
            (output_dir / f"{case.instance_id}.error.txt").write_text(
                str(result.error),
                encoding="utf-8",
            )
            continue

        (output_dir / f"{case.instance_id}.md").write_text(
            result.render_full_markdown(),
            encoding="utf-8",
        )
        (output_dir / f"{case.instance_id}.json").write_text(
            json.dumps(
                {
                    "status": result.execution_status,
                    "token_usage": result.token_usage.model_dump(),
                    "metrics": result.metrics.model_dump(mode="json"),
                    "event_count": len(result.events),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _case_dir(workspace_root: Path, case: BenchmarkCase) -> Path:
    return workspace_root / case.repo_dir
