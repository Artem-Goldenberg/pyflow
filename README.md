# pyflow

`pyflow` is a high-level Python framework for composing agent requests as reusable, typed building blocks and executing them through the OpenHands SDK.

The goal is to make agent automation feel like writing regular Python scripts instead of manually driving CLI/UI sessions.

## Status

Early bootstrap stage. The repository now contains:

- Typed request DSL with immutable composition via `>>` and `@`
- A Pythonic `@tool` decorator for custom function tools
- OpenHands backend adapter (`OpenHandsBackend`) for request execution
- Initial architecture/implementation docs
- OpenHands usage examples and pytest test setup

## Why This Exists

You can describe an agent run as composable blocks:

- What to do (`prompt`, task source, requested output)
- Context (`docs.include`, `docs.exclude`, style profiles, constraints)
- Tooling (`tool.use(...)`, custom function tools)
- Post-steps (`tests.*`, `git.commit()`, `remote.new_mr(...)`)
- Execution backend and model settings

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Minimal pyflow Example

```python
from pyflow import Model, code_style, docs, jira, tool

agent_request = (
    jira.ticket(27253)
    >> "Fix by introducing a new type class" @ code_style.standard()
    @ docs.include("type-inference", "lsp")
    @ docs.exclude("deprecated-code")
    @ tool.use("terminal", "file_editor")
)

model = Model(name="openai/gpt-4.1", api_key_env="OPENAI_API_KEY")
session_log = model.run(agent_request)
print(session_log.final_response)
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
- The current `@tool` decorator supports function tools and auto-registration into OpenHands runtime.
- Interactive notebook/REPL workflow is planned but not fully implemented yet.
