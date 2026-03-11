# pyflow

`pyflow` is a high-level Python framework for composing agent requests as reusable, typed building blocks.

The goal is to make agent automation feel like writing regular Python scripts instead of manually driving CLI/UI sessions.

## Status

Early bootstrap stage. The repository now contains:

- Immutable request DSL core (`Request`, `Step`, `Context`) with `>>` and `@`
- File context helpers (`docs`, `code`) and test steps (`tests`)
- Runtime sink layer (`Agent`, abstract `Model`, `AIModel`, `TestModel`)
- OpenHands execution wiring with conversation return values
- Offline model testing path via OpenHands `TestLLM`
- Architecture/implementation docs
- OpenHands usage examples (raw SDK)
- pytest test setup

Backend abstraction and advanced runtime UX are planned; direct OpenHands runtime support is implemented.

## Why This Exists

You can describe an agent run as composable blocks:

- What to do (`prompt`)
- Context (`docs`, `code`)
- Post-steps (`tests`)

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Minimal pyflow Example

```python
from pydantic import SecretStr
from pyflow import AIModel, Agent, code, docs, tests

request = (
    "Fix the bug." @ docs("plan.md") @ code("app.py")
    >> tests("unit", "integration")
)

model = AIModel(
    name="openai/gpt-4.1",
    base_url="https://api.openai.com/v1",
    api_key=SecretStr("..."),
)
agent = Agent(model=model)
conversation = request >> agent
```

## Offline Runtime Tests

Use `TestModel` to drive deterministic offline tests without real network requests:

```python
from openhands.sdk.llm import Message, TextContent
from pyflow import Agent, TestModel

model = TestModel(
    scripted_responses=(
        Message(role="assistant", content=[TextContent(text="Done")]),
    )
)
agent = Agent(model=model)
```

## OpenHands Examples

See:

- `examples/openhands_quickstart.py`
- `examples/openhands_custom_tool.py`
- `examples/openhands_quickstart.ipynb`

## Docs

- `AGENTS.md` — project intent + coding conventions for future agents
- `ARCHITECTURE.md` — component boundaries and extension model
- `IMPLEMENTATION_PLAN.md` — phased roadmap

## Notes

- OpenHands imports may emit LiteLLM network-fallback warnings in offline environments; this is expected.
- Interactive notebook/REPL workflow is planned but not fully implemented yet.
