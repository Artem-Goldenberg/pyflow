from __future__ import annotations

import pyflow
import pytest
from pathlib import Path
from pyflow import Request, PromptStep, code, docs


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_step_immutability_on_attachment() -> None:
    step = PromptStep(text="Fix the bug.")
    updated = step @ docs("plan.md")

    assert step.attachments == ()
    assert len(updated.attachments) == 1


def test_request_immutability_on_step_append() -> None:
    base = Request(steps=(PromptStep(text="Fix the bug."),))
    updated = base >> pyflow.tests("unit")

    assert len(base.steps) == 1
    assert len(updated.steps) == 2


def test_prompt_attachment_operator() -> None:
    step = "Fix the bug." @ docs("plan.md")

    assert isinstance(step, PromptStep)
    assert len(step.attachments) == 1


def test_prompt_rshift_tests() -> None:
    request = "Fix the bug." >> pyflow.tests("unit")

    assert len(request.steps) == 2
    assert isinstance(request.steps[0], PromptStep)
    assert isinstance(request.steps[1], pyflow.TestStep)


def test_request_matmul_attaches_first_step() -> None:
    request = "Fix the bug." >> pyflow.tests("unit")
    updated = request @ code("app.py")

    assert len(updated.steps[0].attachments) == 1
    assert len(updated.steps[1].attachments) == 0


def test_operator_precedence_attaches_to_test_step() -> None:
    request = "Fix the bug." >> pyflow.tests("unit") @ docs("tests.md")

    assert len(request.steps[1].attachments) == 1


def test_request_rejects_empty_steps() -> None:
    with pytest.raises(ValueError):
        Request(steps=())


def test_request_render_basic(snapshot_regen: bool) -> None:
    request = (
        "Fix the bug." @ docs("plan.md") @ code("app.py")
        >> pyflow.tests("unit", "integration") @ docs("tests.md")
    )
    rendered = request.render()

    assert_snapshot("request_basic", rendered, snapshot_regen)


def test_request_render_multiline(snapshot_regen: bool) -> None:
    request = Request(steps=(PromptStep(text="Line 1\nLine 2"),))
    rendered = request.render()

    assert_snapshot("request_multiline", rendered, snapshot_regen)


def test_request_render_many_steps(snapshot_regen: bool) -> None:
    step_one = "First line\nSecond line" @ docs("notes.md")
    step_two = PromptStep(text="Follow up.") @ code("main.py")
    step_three = pyflow.tests("unit", "integration")

    request = step_one >> step_two >> step_three
    rendered = request.render()

    assert_snapshot("request_many_steps", rendered, snapshot_regen)


def assert_snapshot(name: str, content: str, regen: bool) -> None:
    path = FIXTURES_DIR / f"{name}.txt"
    if regen:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert content == expected
