# pyflow

`pyflow` is a high-level Python framework for composing agent requests as reusable, typed building blocks.

The goal is to make agent automation feel like writing regular Python scripts instead of manually driving CLI/UI sessions.

## Status

Early bootstrap stage. The repository now contains:

- Immutable request DSL core (`Request`, `Step`, `Context`) with `>>` and `@`
- File context helpers (`docs`, `code`) and test steps (`tests`)
- Runtime sink layer (`Agent`, `Session`, abstract `Model`, `AIModel`, `TestModel`)
- OpenHands execution wiring with resumable session return values
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
from pyflow import Agent, Model, code, docs, tests

request = (
    "Fix the bug." @ docs("plan.md") @ code("app.py")
    >> tests("unit", "integration")
)

model = Model.from_api(
    name="openai/gpt-4.1",
    base_url="https://api.openai.com/v1",
    api_key=SecretStr("..."),
)
agent = Agent(model=model)
session = request >> agent
session = "Apply only targeted follow-up changes." >> session
raw_conversation = session.conversation
```

## Structured Output

Use `// output(...)` when the run should finish with JSON that matches a
Pydantic model, and read the parsed value from `session.result`:

```python
from pydantic import BaseModel, SecretStr
from pyflow import Agent, Model, output


class ChunkSummary(BaseModel):
    source: str
    row_count: int


model = Model.from_api(
    name="openai/gpt-4.1",
    base_url="https://api.openai.com/v1",
    api_key=SecretStr("..."),
)
agent = Agent(model=model)
session = "Summarize the chunk." // output(ChunkSummary) >> agent
summary = session.result
raw_json = session.result_text
```

The output contract is request-level metadata. It can be attached to the root
prompt or to an already-built `Request`, but not to later steps in a chained
request.

## Parallel Batch Runs

Use `Agent.parallel(...)` to execute many independent requests concurrently while
preserving input order in the returned results:

```python
from pyflow import Agent, Model, ParallelFailure

agent = Agent(model=Model.test(scripted_responses=(...,)), tools=())
results = agent.parallel(
    chunks,
    lambda chunk: f"Remove anomalies in: {chunk}",
    max_concurrency=8,
    # Optional: set this only for low-rate-limit providers/models.
    max_requests_per_second=1.0,
)

for result in results:
    if isinstance(result, ParallelFailure):
        print("failed:", result.index, result.item, result.phase, result.error)
    else:
        print("finished:", result.execution_status)
```

`Agent.parallel(...)` is synchronous. Successful entries are normal `Session`
objects; failures are returned inline as `ParallelFailure`. Agent tools and
workspace are reused as configured for each worker run. By default there is no
rate cap unless `max_requests_per_second` is set.

## Git Worktree Orchestration

Use `pyflow.gittools` when you want one branch/worktree per agent task and a
separate merge worktree for a resolving agent:

```python
from pyflow import Agent
from pyflow.gittools import GitRepo

repo = GitRepo.open(".")
agent = Agent(model=model)

task_a = repo.create_worktree(
    worktrees_root="../agent-worktrees",
    run_id="run-42",
    task_id="task-a",
)
task_b = repo.create_worktree(
    worktrees_root="../agent-worktrees",
    run_id="run-42",
    task_id="task-b",
)

agent_a = agent.replacing(workspace=task_a.path)
agent_b = agent.replacing(workspace=task_b.path)

merge_tree = repo.create_worktree(
    worktrees_root="../agent-worktrees",
    run_id="run-42",
    task_id="merge",
    start_point="main",
    branch_name="merge/run-42",
)
merge_state = repo.start_merge(merge_tree, "pyflow/run-42/task-a")

if merge_state.conflict_paths:
    merge_repo = GitRepo.open(merge_tree.path)
    merge_status = merge_repo.status()
    merge_diff = merge_repo.diff(left="AUTO_MERGE")
```

The wrapper keeps raw stdout/stderr for agent prompts, but also parses stable
Git porcelain formats for worktree listing, status inspection, diff summaries,
and merge state.

## Offline Runtime Tests

Use `Model.test(...)` to drive deterministic offline tests without real network requests:

```python
from openhands.sdk.llm import Message, TextContent
from pyflow import Agent, Model

model = Model.test(
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
- Each pyflow model owns one live OpenHands `LLM`, so repeated runs through the same model share metrics and other instance-owned LLM state.
- Backend runtime logs are quiet by default at `WARNING`; call `show_backend_logs()` to re-enable OpenHands/LiteLLM INFO output.
- `Model.subscription(...)` may perform OpenHands authentication work during model creation.
- Interactive notebook/REPL workflow is planned but not fully implemented yet.

## Style Notes

- For multiline function definitions, keep the closing `) -> ReturnType:` on one line when it still fits cleanly.
