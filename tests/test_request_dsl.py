from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

from pyflow import PromptStep, Request, TestStep, code, docs, output, tests


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_step_immutability_on_attachment() -> None:
    step = PromptStep(text="Fix the bug.")
    updated = step @ docs("plan.md")

    assert step.attachments == ()
    assert len(updated.attachments) == 1


def test_request_immutability_on_step_append() -> None:
    base = Request(steps=(PromptStep(text="Fix the bug."),))
    updated = base >> tests("unit")

    assert len(base.steps) == 1
    assert len(updated.steps) == 2


def test_prompt_attachment_operator() -> None:
    step = "Fix the bug." @ docs("plan.md")

    assert isinstance(step, PromptStep)
    assert len(step.attachments) == 1


def test_prompt_rshift_tests() -> None:
    request = "Fix the bug." >> tests("unit")

    assert len(request.steps) == 2
    assert isinstance(request.steps[0], PromptStep)
    assert isinstance(request.steps[1], TestStep)


def test_request_matmul_attaches_first_step() -> None:
    request = "Fix the bug." >> tests("unit")
    updated = request @ code("app.py")

    assert len(updated.steps[0].attachments) == 1
    assert len(updated.steps[1].attachments) == 0


def test_operator_precedence_attaches_to_test_step() -> None:
    request = "Fix the bug." >> tests("unit") @ docs("tests.md")

    assert len(request.steps[1].attachments) == 1


def test_prompt_floordiv_output_creates_request() -> None:
    request = "Summarize the chunk." // output(_ChunkSummary)

    assert isinstance(request, Request)
    assert request.output_spec is not None
    assert request.output_spec.model_type is _ChunkSummary


def test_request_floordiv_output_is_immutable() -> None:
    base = "Summarize the chunk."
    request = base // output(_ChunkSummary)
    updated = request >> tests("unit")

    assert request.output_spec is not None
    assert updated.output_spec is request.output_spec
    assert len(request.steps) == 1
    assert len(updated.steps) == 2


def test_operator_precedence_attaches_output_before_rshift() -> None:
    request = "Summarize the chunk." // output(_ChunkSummary) >> tests("unit")

    assert request.output_spec is not None
    assert len(request.steps) == 2
    assert isinstance(request.steps[1], TestStep)


def test_output_contract_rejects_later_step_attachment() -> None:
    with pytest.raises(ValueError, match="request root"):
        _ = output(_ChunkSummary).__rfloordiv__(tests("unit"))


def test_request_rejects_duplicate_output_contract() -> None:
    request = "Summarize the chunk." // output(_ChunkSummary)

    with pytest.raises(ValueError, match="already has an output contract"):
        _ = request // output(_ChunkSummary)


def test_output_rejects_non_pydantic_models() -> None:
    with pytest.raises(TypeError, match="BaseModel"):
        output(cast(type[BaseModel], dict))


def test_request_rejects_empty_steps() -> None:
    with pytest.raises(ValueError):
        Request(steps=())


def test_request_render_basic(snapshot_regen: bool) -> None:
    request = (
        "Fix the bug." @ docs("plan.md") @ code("app.py")
        >> tests("unit", "integration") @ docs("tests.md")
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
    step_three = tests("unit", "integration")

    request = step_one >> step_two >> step_three
    rendered = request.render()

    assert_snapshot("request_many_steps", rendered, snapshot_regen)


def test_request_render_with_output_contract(snapshot_regen: bool) -> None:
    request = "Summarize the chunk." @ docs("notes.md") // output(_ChunkSummary) >> tests(
        "unit"
    )
    rendered = request.render()

    assert_snapshot("request_output_contract", rendered, snapshot_regen)


def assert_snapshot(name: str, content: str, regen: bool) -> None:
    path = FIXTURES_DIR / f"{name}.txt"
    if regen:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert content.rstrip("\n") == expected.rstrip("\n")


class _ChunkSummary(BaseModel):
    source: str
    row_count: int
