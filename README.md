# pyflow

`pyflow` is a high-level Python framework for composing agent requests as reusable, typed building blocks.

The goal is to make agent automation feel like writing regular Python scripts instead of manually driving CLI/UI sessions.

## Status

Early bootstrap stage. The repository now contains:

- Immutable request DSL core (`Request`, `Step`, `Context`) with `>>` and `@`
- File context helpers (`docs`, `code`) and test steps (`tests`)
- Architecture/implementation docs
- OpenHands usage examples (raw SDK)
- pytest test setup

Execution backends and model/runtime integration are planned but not implemented yet.

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
from pyflow import code, docs, tests

request = (
    "Fix the bug." @ docs("plan.md") @ code("app.py")
    >> tests("unit", "integration")
)

print(request.render())
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
