from __future__ import annotations

from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient


def test_notebook_assignment_then_session_renders_widget_in_both_cells() -> None:
    notebook = _notebook_from_fixture("session_assignment_then_render.py")

    executed = _execute_notebook_or_skip(notebook)
    assignment_outputs = executed.cells[1].outputs
    assignment_markdown = _output_with_mime(assignment_outputs, "text/markdown")
    session_output = executed.cells[2].outputs[0]

    assert len(assignment_outputs) == 1
    assert assignment_markdown.output_type == "display_data"
    assert "## pyflow session" not in assignment_markdown.data["text/markdown"]
    assert "Status: **Finished**" in assignment_markdown.data["text/markdown"]
    assert "System Prompt" not in assignment_markdown.data["text/markdown"]
    assert (
        "application/vnd.jupyter.widget-view+json"
        not in assignment_markdown.data
    )

    assert session_output.output_type == "display_data"
    assert "text/markdown" in session_output.data
    assert "## pyflow session" not in session_output.data["text/markdown"]
    assert "Status: **Finished**" in session_output.data["text/markdown"]
    assert "System Prompt" in session_output.data["text/markdown"]
    assert "### User" in session_output.data["text/markdown"]
    assert "Hi" in session_output.data["text/markdown"]

    assert "application/vnd.jupyter.widget-view+json" not in session_output.data


def test_notebook_bare_expression_hides_the_session_auto_display_payload() -> None:
    notebook = _notebook_from_fixture("session_bare_expression.py")

    executed = _execute_notebook_or_skip(notebook)
    outputs = executed.cells[1].outputs
    markdown_output = _output_with_mime(outputs, "text/markdown")

    assert len(outputs) == 1
    assert markdown_output.output_type == "display_data"
    assert "## pyflow session" not in markdown_output.data["text/markdown"]
    assert "Status: **Finished**" in markdown_output.data["text/markdown"]
    assert "System Prompt" not in markdown_output.data["text/markdown"]
    assert "application/vnd.jupyter.widget-view+json" not in markdown_output.data


def test_notebook_session_run_suppresses_blank_backend_log_outputs() -> None:
    notebook = _notebook_from_fixture("session_assignment_blank_warning.py")

    executed = _execute_notebook_or_skip(notebook)
    outputs = executed.cells[1].outputs

    assert len(outputs) == 1
    assert not any(_is_empty_rich_html_output(output) for output in outputs)


def _output_with_mime(
    outputs: list[nbformat.NotebookNode],
    mime_type: str,
) -> nbformat.NotebookNode:
    for output in outputs:
        data = output.get("data", {})
        if mime_type in data:
            return output
    raise AssertionError(f"No notebook output contained MIME type {mime_type!r}")


def _is_empty_rich_html_output(output: nbformat.NotebookNode) -> bool:
    data = output.get("data", {})
    html = data.get("text/html")
    if not isinstance(html, list) or len(html) != 1:
        return False
    if data.get("text/plain") != []:
        return False
    return html[0].startswith("<pre ") and html[0].endswith("></pre>\n")


def _execute_notebook_or_skip(
    notebook: nbformat.NotebookNode,
) -> nbformat.NotebookNode:
    client = NotebookClient(
        notebook,
        kernel_name="python3",
        shutdown_kernel="immediate",
        timeout=120,
        resources={"metadata": {"path": str(Path.cwd())}},
    )
    try:
        return client.execute()
    except PermissionError as exc:
        pytest.skip(f"Notebook kernel launch is not permitted here: {exc}")
    finally:
        if getattr(client, "km", None) is not None:
            client._cleanup_kernel()


def _notebook_from_fixture(name: str) -> nbformat.NotebookNode:
    fixture_path = Path(__file__).parent / "fixtures" / "notebooks" / name
    source = fixture_path.read_text()
    cells: list[nbformat.NotebookNode] = []
    current_lines: list[str] = []
    seen_cell = False

    for line in source.splitlines(keepends=True):
        if line.startswith("# %%"):
            seen_cell = True
            if current_lines:
                cells.append(
                    nbformat.v4.new_code_cell("".join(current_lines).strip())
                )
                current_lines = []
            continue
        if not seen_cell:
            continue
        current_lines.append(line)

    if current_lines:
        cells.append(nbformat.v4.new_code_cell("".join(current_lines).strip()))

    return nbformat.v4.new_notebook(cells=cells)
