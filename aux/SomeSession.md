This project is a very high level python framework for manipulating agents.


It will allow the user to run agent requests, like we now do using the agent's cli or UI tools,
but this framework allows for creating quick python scripts, which would typically contain and describe an agent request by composing reusable blocks:
    - what prompt, what model, what tools to use, what documentation and other files/code classes to add to the context,
        what skills/general prompts to include and so on...
    - also what should be done on completing the request, commit? createPR? or ensure some particular test passes
    - maybe some other things like what docs to explicitly exclude from the model context, or some more general
        context management machinery
    - also this request should allow to require/add constrains for parallelization, and other orchestration of many agents

what I want to achive first is the ability to compose requests which look like these:

```python
agent_request = (
    jira.ticket(27253)
        >> "Fix by introducing a new type class"
        @ code_stye.standard()
        @ docs.include("type-inference", "lsp", web=attlasian.feature_meeting("May, 4"))
        @ docs.exclude("deprecated-code")
        @ java.code_model.classes.FunctionDefType
        @ tool.use(tools.standard, tools.python.read, tools.python.rename, tools.bash("grep", "gradle"))
        >> tests.TypeInferenceTests
        >> git.commit()
        >> remote.newMR(review=Team.MikhailV)
)
session_log = model.Opus35.run(agent_request)
# Perhaps then reuse this `session_log` in new requests
```

So this framework is intended to be used similar to an agent CLI/UI application like Warp, codex,
claude-code, etc, etc...

So it should support programmatically composing prompts, adding tools, skills, choosing models,
controling what context and tools are available in each request and basically everything what the
agent apps can do, but programmatically.

Another crutial thing for this framework is the extensibility of it.
It should make easy for the user to add his own tools, skills and
other stuff that UI/cli application allow the user now.
In addition, user will be able to create reusable patterns out of the building blocks this framework provides. 
For a concrete example here, to add a custom tool, the user needs to subclass the `Tool` class
and implement some methods describing the tool and for the model to be able to call that tool 
(try to make those interfaces and their customization as pythonic as possible)


To imporve interactive control, those agent request script should also probably support running
inside a jupyter notebook in the future, or at least start some kind of interactive session in the
console, when run. Because when they are run the agent will like start working, will try to call
some tools, use skills and such, so the "output" session need to be able to represent that, and
ideally allow the user somehow to provide corrections based on the progress it sees.

As for backend to access agent's capabilities, I think there are no agent APIs which you can
just call upong right now, so I'm planning to use lang chain/lang graph libraries to translate
these agent requests into their pipelines and execute them. Let me know if you have any ideas
about this, perhaps any suggestions how it can be done easier. 



This is an ambitious and interesting project. Let me first look at what exists in the repo, then share my thoughts.

**Command Executed:**
```bash
ls -la /Users/goldenberg/Developer/pyflow
```

**Output:**
```
total 0
drwxr-xr-x@   2 goldenberg  staff    64 Mar  6 00:47 .
drwxr-xr-x@ 114 goldenberg  staff  3648 Mar  6 00:47 ..
```

Empty repo. Let me share my analysis and then we can plan this out.

**On the DSL design:** Your operator-based composition (`>>`, `@`) is expressive, but there are some subtleties worth discussing — `>>` typically means "then" (sequencing), and `@` is being overloaded for "with context/config". That's workable via `__rshift__` and `__matmul__` dunder methods, though we should be deliberate about precedence (`@` binds tighter than `>>` in Python, which actually works in your favor — context/config binds to the nearest step before sequencing kicks in).

**On the backend — LangChain/LangGraph vs alternatives:**

LangChain/LangGraph is a reasonable choice but has tradeoffs:
- **Pros:** Large ecosystem, tool/model abstractions already exist, LangGraph handles stateful agent orchestration with cycles and branching.
- **Cons:** Heavy abstraction layers, API surface changes frequently, can be hard to debug, and it forces your execution model to fit theirs.

**Alternatives worth considering:**
1. **Direct model API calls + your own orchestration.** Anthropic, OpenAI, etc. all have tool-use APIs now. Your framework could translate the composed request into a tool-use loop directly. This gives you full control and far less dependency weight.
2. **LiteLLM** as a thin model abstraction (unified API across providers) + your own agent loop. Much lighter than LangChain.
3. **PydanticAI** — newer, lighter agent framework built on Pydantic. Cleaner than LangChain, typed, and closer in spirit to what you're building.

**My recommendation:** Start with direct API calls (via `litellm` or raw SDKs) and build your own agent loop. Your framework *is* the orchestration layer — wrapping LangChain around it adds indirection without much value. The core agent loop (send messages → get tool calls → execute tools → feed results back) is straightforward to implement, and you'll want full control over it anyway for features like interactive sessions, parallelization constraints, and session logging.

**Key architectural pieces I see:**

1. **Request DSL** — the composable expression tree (`AgentRequest`, operators)
2. **Request compiler** — flattens the DSL into a concrete execution plan (system prompt, tools, model config, post-actions)
3. **Agent runtime** — the tool-use loop that executes against a model API
4. **Tool/Skill system** — base classes users subclass, with a registry
5. **Session** — captures the execution trace, supports interactive feedback
6. **Integrations** — `jira`, `git`, `docs`, etc. as bundled modules

Want me to create a detailed implementation plan? I can lay out the module structure, core abstractions, and a phased build order.


Investigate more carefully whether some similar frameworks to this exist? Or perhaps they are more lower level than mine? Does that mean I can build on top of them? What about OpenAI Agents SDK or OpenHands or Microsoft Agent Framework or AIGen, and so on... 
Also (I dug really deep for this) I found some undocumented python framework, that aider exposes: https://aider.chat/docs/scripting.html please explain what this aider even is, because it seems like an agent, but the word 'agent' is never mentioned there, so i don't know is it worth something or not?

Let me research each of these frameworks and the aider scripting API.
Here's my analysis after digging into all of these. This significantly changes my recommendations from before.

---

## What is Aider?

Aider is AI pair programming in your terminal. It's a terminal-based AI pair-programming tool that connects large language models to your local Git repository, editing code in place and tracking every change with Git commits. It is absolutely an agent in the modern sense — it has a tool-use loop (read files, edit files, run commands), it maintains context (repo map), and it acts autonomously. The word "agent" wasn't commonly used when aider was created, so they market it as "AI pair programming."

The Python scripting API you found is real but limited. The page itself states the API "is not officially supported or documented, and could change in future releases." It's essentially just instantiating aider's internal `Coder` class and calling `run()` on it — there's no composition, no programmatic tool control, no structured output. It's useful for simple batch operations (apply the same instruction to many files) but not as a foundation to build on.

---

## Framework Landscape — Tiered by Abstraction Level

### Tier 1: Coding Agent SDKs (closest to your use case)

**Claude Agent SDK** (`claude-agent-sdk`) — This is the most relevant discovery. It lets you build AI agents that autonomously read files, run commands, search the web, edit code, and more. The Agent SDK gives you the same tools, agent loop, and context management that power Claude Code, programmable in Python and TypeScript. Unlike simple queries, ClaudeSDKClient additionally enables custom tools and hooks, both of which can be defined as Python functions. A custom tool is a Python function that you can offer to Claude. Custom tools are implemented as in-process MCP servers that run directly within your Python application. This is essentially what you described wanting — programmatic access to a full coding agent — but only for Claude models.

**OpenHands Software Agent SDK** — A set of Python and REST APIs for building agents that work with code. OpenHands is the leading open source framework for coding agents. It's MIT-licensed, and can work with any LLM. It has tools for file editing, terminal access, task tracking, and browser interaction. You can define agents in code, then run them locally, or scale to 1000s of agents in the cloud. Model-agnostic, unlike Claude Agent SDK.

### Tier 2: General Agent Frameworks

**OpenAI Agents SDK** — A lightweight yet powerful framework for building multi-agent workflows. It is provider-agnostic, supporting the OpenAI Responses and Chat Completions APIs, as well as 100+ other LLMs. Features include agents as tools, handoffs, guardrails, human in the loop, sessions, tracing, and realtime agents. Good building blocks, but it's a general-purpose agent framework — you'd still need to build all the coding-specific tools yourself.

**PydanticAI** — A Python agent framework designed to help you quickly, confidently, and painlessly build production grade applications with Generative AI. Its killer feature is full type-safety designed to give your IDE as much context as possible for auto-completion and type checking. Also supports MCP, A2A, and UI event stream standards and durable execution that can preserve progress across API failures. Model-agnostic with excellent support for every major provider.

**Microsoft Agent Framework** — Combines AutoGen's simple agent abstractions with Semantic Kernel's enterprise features — session-based state management, type safety, middleware, telemetry — and adds graph-based workflows for explicit multi-agent orchestration. AutoGen and Semantic Kernel have entered maintenance mode, with all future development centered on this unified platform. Heavy, enterprise-oriented, deep Azure integration. Probably overkill and too opinionated for your use case.

---

## How This Changes Your Architecture

The landscape has shifted dramatically since my first analysis. You do **not** need to build the agent loop and coding tools yourself. There are now two strong options for the execution backend:

**Option A: Claude Agent SDK as backend.** You get Claude Code's entire toolset (file editing, bash, search, etc.) for free. Your DSL compiles down to `query()` / `ClaudeSDKClient` calls with the right `ClaudeAgentOptions`. Downside: locked to Claude models.

**Option B: OpenHands SDK as backend.** Model-agnostic, MIT-licensed, has coding tools built in. Your DSL compiles to `Conversation` + `Agent` objects. More portable.

**Option C: PydanticAI as the model layer + build your own coding tools.** Most control, most work, but cleanest architecture for a composable DSL since PydanticAI's type-safe tool/agent model aligns well with your Pythonic design goals.

**My revised recommendation:** Consider a layered approach:
1. Your DSL layer (the `>>` / `@` composition) — this is genuinely novel and doesn't exist in any framework
2. A "backend adapter" abstraction that can target multiple execution backends
3. Start with Claude Agent SDK or OpenHands SDK as the first adapter — get working end-to-end fast
4. Use PydanticAI if you want to build a more custom adapter with finer control

The key insight is: **none of these frameworks provide a composable request DSL**. They all require you to imperatively configure agents. Your project's value-add is the declarative composition layer on top.

Want me to create a revised implementation plan incorporating these findings?



Ok, after I literally two days of debating myself and researching all this framework stuff
I've decided I will use the OpenHands SDK. Yes it's not perfect, it may be too abstract for
some of my future goals with this. But it is beautiful and clean, so I don't want to deal
with all those langchain production things. We will use this for now and see how we can bend
this framework when we the need comes.
Just in case the repositor of this SDK: https://github.com/OpenHands/software-agent-sdk/tree/main
And the documentation: https://docs.openhands.dev/sdk


For now, initialize the project. For now don't create a lot of fluf folders, make it as flat as 
possible. Create .venv, create a repository
with readme and AGENTS.md, specifying the idea and documentation of the project 
We've described above. So that it would be clear for you and other agents what needs to be done next.
Feel free to add other documentation files, perhaps describing an implementation plan and the
architecture of components.

As for the main implementation steps, my current understanding is the following:
- Think about more usages in code for this frameworks, like the request example above,
    but need more examples 
- Decide how the agent interaction is actually going to happen. For now I think the simplest
    and universal solution would be to integrate it into the python repl, requesting input
    when tool approve is needed and so on. So for that need to investigate and decide on 
    a sane terminal output library.
- Define this framework's main abstractions. One of which will certanly be a `Request` to
    which you can attach stuff with `@ context` or `@ tool`. Also we must implement the `@tool`
    decorator, because as I understand open hands sdk doesn't have that. Also I think
    we would need our separate `Agent` class, to which you can send the Request (via `>>`).
    Agent is
    composes `Model` class with the stuff like tools, skills, context. We will need to create
    some predefined agents with some default predefined set of tools, skills, etc... And another
    thing I want is a convinient Model class, to which you can just specify and endpoint + key and
    it will fetch all available models for you and *generate* static class variables with those
    models defined! Perhaps there is stuff I'm missing here.
- Connect those abstraction to the OpenHands SDK ones. And get a working framework for agent
 requests.

If you have any suggestions on this plan, then let me know

and also add preferences: 
    - Always use type annotations, don't hesitate in using TypeVars and other advanced typing stuff
    - Sort imports by: `import...`, and only then `from ... import...`
    - Use abstractclasses and dataclasses when appropriate

also create a couple of examples (files/notebooks) of how to use opendhands SDK library,
I don't know how to use it.

Also don't forget about tests, they are very important. I want you to set up testing via
pytest from the start.

Let me first research the OpenHands SDK API, then set everything up.
Good research done. Now let me set everything up.
UpdateTodos: 10 items

**Command Executed:**
```bash
git init /Users/goldenberg/Developer/pyflow
```

**Output:**
```
Initialized empty Git repository in /Users/goldenberg/Developer/pyflow/.git/
```



**Diff:**
```diff
--- /Users/goldenberg/Developer/pyflow/pyproject.toml
+++ /Users/goldenberg/Developer/pyflow/pyproject.toml
@@ -0,0 +1,29 @@
+[project]
+name = "pyflow"
+version = "0.1.0"
+description = "A high-level Python DSL for composing and executing AI agent requests"
+readme = "README.md"
+requires-python = ">=3.12"
+license = "MIT"
+dependencies = [
+    "openhands-sdk>=1.0.0",
+    "openhands-tools>=1.0.0",
+    "rich>=13.0",
+]
+
+[project.optional-dependencies]
+dev = [
+    "pytest>=8.0",
+    "pytest-asyncio>=0.24",
+]
+
+[build-system]
+requires = ["hatchling"]
+build-backend = "hatchling.build"
+
+[tool.pytest.ini_options]
+testpaths = ["tests"]
+asyncio_mode = "auto"
+
+[tool.hatch.build.targets.wheel]
+packages = ["pyflow"]

```





**Diff:**
```diff
--- /Users/goldenberg/Developer/pyflow/.gitignore
+++ /Users/goldenberg/Developer/pyflow/.gitignore
@@ -0,0 +1,12 @@
+__pycache__/
+*.py[cod]
+*.egg-info/
+dist/
+build/
+.venv/
+.env
+*.egg
+.pytest_cache/
+.mypy_cache/
+.ruff_cache/
+*.so

```



MarkAsCompleted: 1 items
Now creating the venv and installing deps. Then I'll create all the documentation and code files.

**Command Executed:**
```bash
uv venv /Users/goldenberg/Developer/pyflow/.venv --python 3.12
```

**Output:**
```
zsh: command not found: uv
```


**Command Executed:**
```bash
python3 --version
```

**Output:**
```
Python 3.12.3
```


```bash
python3 -m venv /Users/goldenberg/Developer/pyflow/.venv
```

**Current Output:**
```

<|cursor|>
```

Subagent: 45483b13-90e8-48bd-995b-e95b4cf36388


```bash
/Users/goldenberg/Developer/pyflow/.venv/bin/pip install --upgrade pip && /Users/goldenberg/Developer/pyflow/.venv/bin/pip install openhands-sdk openhands-tools rich pytest pytest-asyncio
```

**Current Output:**
```
Requirement already satisfied: pip in ./.venv/lib/python3.12/site-packages (24.0)
Collecting pip
  Using cached pip-26.0.1-py3-none-any.whl.metadata (4.7 kB)
Using cached pip-26.0.1-py3-none-any.whl (1.8 MB)
Installing collected packages: pip
  Attempting uninstall: pip
    Found existing installation: pip 24.0
    Uninstalling pip-24.0:
      Successfully uninstalled pip-24.0
<|cursor|>
```


>> Please continue with a plan
