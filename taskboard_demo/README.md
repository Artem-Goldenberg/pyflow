# Taskboard Demo

This directory is a purpose-built repository for demonstrating that `pyflow`
can manage multiple agents against one codebase using Git worktrees.

The base application is intentionally small:

- `taskboard add "Buy milk"`
- `taskboard list`
- `taskboard done 1`
- tasks persist to `taskboard.json`

The demo is designed around two parallel feature tasks that both touch the same
files and therefore produce a meaningful merge:

1. Add priority support.
2. Add due-date support.

The merge agent then has to combine:

- the task model
- JSON persistence
- CLI argument parsing
- list rendering
- sorting rules
- tests

## Files The Agents Should Touch

- `taskboard/models.py`
- `taskboard/storage.py`
- `taskboard/cli.py`
- `tests/test_cli.py`
- `README.md`

## Base Commands

Use the local project interpreter or an activated virtual environment:

```bash
python -m pytest tests
python -m taskboard.cli --db taskboard.json add "Buy milk"
python -m taskboard.cli --db taskboard.json list
python -m taskboard.cli --db taskboard.json done 1
```

## Demo Notebook

Open [`multi_agent_demo.ipynb`](multi_agent_demo.ipynb) in Jupyter from the main `pyflow` repository.

The notebook will:

1. Copy this project into a disposable standalone Git repository.
2. Show the base CLI behavior quickly.
3. Create one worktree per feature task.
4. Run two feature agents in parallel.
5. Start a merge worktree and show the conflict state before resolution.
6. Ask a third agent to resolve the merge with wrapper-provided Git status and diff context.
7. Finalize the merge and show the app with both features implemented.

The notebook uses separate `Agent` instances plus Python concurrency rather than
`Agent.parallel(...)`, because each Git worktree needs its own isolated
`workspace` path.
