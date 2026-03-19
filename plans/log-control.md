# Deterministic Logging Control For Pyflow Runtime

## Summary

Pyflow already executes requests through OpenHands-backed models, but logging and observability are currently controlled by a mix of hardcoded defaults and ambient environment variables. This task introduces a pyflow-owned logging control API with one global policy and per-model overrides, so local completion logs, remote Laminar-style observability, and LiteLLM/OpenHands text logs are enabled only when pyflow explicitly asks for them. After implementation, testing must confirm policy precedence, correct local file routing, no unwanted remote emission, and no import-time telemetry activation leaks.

## Introduction

### Prerequisites

- **Documentation**:
  - [Project conventions and testing rules](AGENTS.md)
  - [Architecture: Runtime Model Layer, Agent Layer, Session Layer, OpenHands SDK Integration](ARCHITECTURE.md)
  - [Current high-level roadmap, especially Execution UX](IMPLEMENTATION_PLAN.md)
- **Related code**:
  - [Public package exports](pyflow/__init__.py)
  - [Model abstraction and current `AIModel.build_llm()` behavior](pyflow/model.py)
  - [Agent runtime construction](pyflow/agent.py)
  - [Session continuation behavior](pyflow/session.py)
  - [Current runtime tests](tests/test_runtime.py)
  - [Current telemetry-disabling test bootstrap](tests/conftest.py)
  - Installed OpenHands SDK sources currently used by the local environment:
    - `.venv/lib/python3.12/site-packages/openhands/sdk/__init__.py`
    - `.venv/lib/python3.12/site-packages/openhands/sdk/agent/agent.py`
    - `.venv/lib/python3.12/site-packages/openhands/sdk/observability/laminar.py`
    - `.venv/lib/python3.12/site-packages/openhands/sdk/observability/utils.py`
    - `.venv/lib/python3.12/site-packages/openhands/sdk/llm/llm.py`
  - Installed LiteLLM sources currently used by the local environment:
    - `.venv/lib/python3.12/site-packages/litellm/__init__.py`
    - `.venv/lib/python3.12/site-packages/litellm/_logging.py`

### Problem

Currently, pyflow can successfully execute provider-backed and test-backed requests through a compact `Model`/`Agent` API.

But logging control is fragmented and partially outside pyflow's control. `AIModel.build_llm()` currently hardcodes OpenHands completion logging on and writes to a fixed folder, OpenHands observability can activate from process environment variables or `.env` files during import, LiteLLM also loads environment-based logging configuration during import, and tests already need a bootstrap patch to suppress those side effects. The result is that users must manage logging behavior by editing environment variables instead of by using the framework API.

This task solves that problem by making pyflow the single owner of logging intent. Users must be able to declare logging behavior once globally and override it per model, while pyflow ensures that the effective configuration determines which logs are emitted, at what level, and to which destinations.

### Task

Pyflow's runtime stack has several distinct logging surfaces: ordinary textual logger output, LLM completion artifacts written to disk, and remote observability/tracing exported to an external backend such as Laminar. These surfaces are related, but they are not interchangeable. A logging level is not the same thing as a log sink, and a local completion archive is not the same thing as remote telemetry. The task belongs to the runtime configuration area of the framework and must make those surfaces first-class and explicitly configurable.

The current task is to add a pyflow logging-control API that covers exactly two configuration scopes: a global default policy for the whole process and a per-model override policy for individual model instances. The task must not require users to comment or uncomment environment variables in normal usage. The task must define explicit control over:

- textual logger verbosity for pyflow-owned logging, OpenHands logging, and LiteLLM logging
- local completion logging, including explicit enable/disable state and an explicit destination file or file-backed sink
- remote observability/tracing, including explicit enable/disable state and explicit remote destination configuration
- policy precedence between the global policy and a model-specific override
- explicit disable semantics, so that a disabled remote logging policy means pyflow does not emit remote logs even when relevant environment variables are present

The task scope is intentionally limited. It must not redesign the `Request` DSL, must not add a UI for viewing logs, and must not broaden configuration scope beyond global defaults plus per-model overrides. Per-run temporary overrides may be considered later, but they are not part of this task.

Completing this task must produce the following user-facing changes.

First, users must be able to declare one global logging policy in pyflow code. The exact example values below are illustrative, but the behavior is required:

```python
from pyflow.logging import (
    CompletionLogs,
    LogLevel,
    LogPolicy,
    LoggingConfig,
    Observability,
    TextLogs,
    configure_logging,
)

configure_logging(
    LoggingConfig(
        strict=True,
        inherit_process_env=False,
        default=LogPolicy(
            pyflow=TextLogs(level=LogLevel.WARNING),
            openhands=TextLogs(level=LogLevel.WARNING),
            litellm=TextLogs(level=LogLevel.ERROR),
            completions=CompletionLogs.off(),
            observability=Observability.off(),
        ),
    )
)
```

Expected behavior:

- This configuration becomes the default for subsequently created or executed models in the current process.
- With `strict=True` and `inherit_process_env=False`, ambient telemetry-related environment variables are not enough to turn remote logging on by themselves.
- Completion artifacts are not written unless a model explicitly enables them.
- Text logger verbosity follows the declared policy instead of backend defaults.

Second, users must be able to override the global policy per model at model construction time. The exact endpoint values and file paths below are illustrative, but the behavior is required:

```python
from pyflow import AIModel
from pyflow.logging import (
    CompletionLogs,
    JsonlFileSink,
    LaminarSink,
    LogPolicy,
    Observability,
)

planner = AIModel(
    name="openai/gpt-5",
    api_key=...,
    logging=LogPolicy(
        completions=CompletionLogs.jsonl(
            sink=JsonlFileSink("logs/planner-completions.jsonl"),
        ),
        observability=Observability.laminar(
            sink=LaminarSink(
                endpoint="https://laminar.example.invalid",
                api_key=...,
            ),
        ),
    ),
)
```

Expected behavior:

- This model writes completion logs only to the configured local destination.
- This model sends remote observability data only to the configured remote sink.
- Other models continue to use the global policy unless they also declare overrides.
- The model-level override must be explicit and readable from the constructor, because model instances are the unit at which users reason about provider/runtime behavior.

Third, users must be able to keep one model quiet while another model is verbose within the same application configuration surface:

```python
reviewer = AIModel(
    name="openai/gpt-4.1-mini",
    api_key=...,
    logging=LogPolicy(
        completions=CompletionLogs.off(),
        observability=Observability.off(),
    ),
)
```

Expected behavior:

- `planner` and `reviewer` may coexist with different logging policies.
- `reviewer` must not write completion files or emit remote traces merely because another model enabled them.
- This behavior must hold even when environment variables that would normally activate OpenHands or LiteLLM observability are present in the shell or `.env`.

Fourth, users must be able to rely on pyflow for log control instead of on backend import order. A configuration such as the following must keep remote logging off even when environment variables are present. The environment variable values are illustrative:

```python
import os

os.environ["LMNR_PROJECT_API_KEY"] = "example"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://collector.example.invalid"

configure_logging(
    LoggingConfig(
        strict=True,
        inherit_process_env=False,
        default=LogPolicy(observability=Observability.off()),
    )
)
```

Expected behavior:

- Pyflow's explicit policy wins.
- Users are not required to manually edit those environment variables just to run locally without remote telemetry.
- If the backend runtime cannot honor that guarantee after eager import, pyflow must treat that as a pyflow runtime problem to solve rather than as a user responsibility.

#### Notes

- This task must clearly distinguish current behavior from desired behavior in code and documentation. In particular, the current hardcoded completion logging in `AIModel.build_llm()` and the import-time observability activation in OpenHands/LiteLLM are part of the problem statement, not acceptable steady-state behavior.
- This task is about deterministic runtime control, not merely about exposing more knobs. It is insufficient to add public configuration fields if ambient backend state can still silently override them.
- The task must keep the framework usable in test environments without network side effects or mandatory telemetry setup.
- This task may change internal backend bootstrapping behavior as needed, but that mechanism is not itself a user-facing requirement. The user-facing requirement is that explicit pyflow policy determines logging behavior.
- New public API names introduced by this task plan:
  - `pyflow.logging.configure_logging`
  - `pyflow.logging.LoggingConfig`
  - `pyflow.logging.LogPolicy`
  - `pyflow.logging.LogLevel`
  - `pyflow.logging.TextLogs`
  - `pyflow.logging.CompletionLogs`
  - `pyflow.logging.Observability`
  - `pyflow.logging.JsonlFileSink`
  - `pyflow.logging.LaminarSink`
  - `AIModel.logging`

### Review notes

1. Reworked the task from a generic observability upgrade into a single focused runtime logging-control task, because the underlying issue is explicit configuration ownership rather than telemetry feature breadth.
2. Added concrete current-behavior references from the inspected codebase, including `AIModel.build_llm()` hardcoding and the existing test bootstrap workaround, so the implementer can distinguish symptoms from target behavior.
3. Narrowed scope to global plus per-model policy only and explicitly excluded per-run overrides, UI work, and DSL changes, to keep the first milestone aligned with the user's stated need.
4. Added required user-facing examples for global defaults, per-model overrides, mixed-model coexistence, and env-var suppression so the desired semantics are testable and unambiguous.
5. Added an explicit list of all new public API names mentioned in the plan to satisfy the project planning rules and make later implementation review easier.
