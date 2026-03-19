---
name: planning
description: Create a two-stage implementation plan for non-trivial engineering tasks: first a reviewed task specification, then implementation and testing details. Use for software changes that need careful scoping before coding. Do not use for trivial questions, brainstorming, or direct implementation requests.
user-invocable: true
---


When asked to make a plan for solving an issue, split it in two parts:
1. summary and task specification part
2. implementation and testing part

If there are several unrelated problems to solve, then ask which one to make a plan for first,
**DO NOT** try to put them all in one plan together, need to pick one!

After you've created and carefully reviewed the first part stop, and send it to me.
I can make comments or edit it manually, I can even start a session by pasting a 
finished first part of the plan and ask you to improve it or to straight away write 
a second part based on this first one.
The same applies to the second part, after you've created  and carefully reviewed it 
based on the first part, give it to me for review. We can iterate on it for a while,
and once I told you it is ok, I can ask you to go and actually implement this full plan.
Or again, I can start the session by giving you a finished plan and ask you to 
implement it right away.

Next, I will give you general instructions concerning the plan construction.
All the general instructions I'm about to give you apply to both parts of the plan.

When producing both parts of the plan keep in mind the following things:
- You don't know who will be the implementor of the plan. It might be you,
    or it might be you in another session without the current context,
    or it may be even another human. So writhe the plan accordingly,
    **DO NOT** skip details, which you though about, write them all 
    out in the appropriate sections. 
    Carefully list all prior project-specific knowledge which is needed to implement the plan.

- After creating first draft of each part of the plan, **review** it 3-5 times before your final
    answer. While reviewing, double check the details, question your decisions
    and try hard to find better ways to do it. It is normal, and even good if you
    end up fully rewriting the plan part several times during review. Append
    your incremental review improvements at the end of the final plan part.

- Try to write the non-structured text as concise as possible, but do not hurt the
    understandability of the text by throwing away the important details. The goal
    is to make the plan as quick and easy to read for humans as possible, but complete as well.
    I know it's hard, but you can revise the wording iteratively across several review passes. 

- The definition of modal words is as follows:
    - must = required
    - should = recommended
    - may = optional / future extension

- Always distinguish current behavior from desired behavior 
    after inspecting the code.

- Every new public API name mentioned in the plan must be 
    explicitly listed as new.

Now I will describe the precise format for both parts of the plan:

# Concise task title (like an article title)

## Summary (high level summary of the task and the plan as a whole)

In 1-2 sentences state the problem this task is going to solve. Then
give a general overview of the task itself and give a very high-level, 
almost non-technical description of the solution. Finish with the
high level, quick enumeration of things which will need to be tested for,
after the solution is implemented.

This section must state what the plan is about, like an article's abstract section states
what the article is about.

## Introduction (project-specific context, the implementer needs to implement the plan)

### Prerequisites

Here you can list all the resources that the implementer needs to get acquainted with in
order to even understand the problem.

- **Documentation**: List of documentation files (or specific sections in them)
    and URLs which needs to be explored before implementing the plan.

- **Related code**: Current source files

### Problem

First, of the actual problem we are trying to solve.

First, in one sentence, state the area in which the problem occurs, with a positive accent, 
for example:
"Currently, our parser can parse all python 12 syntax.", or
"Our type inference system now successfully supports all basic language constructions."

And then, with a negative accent state the problem at hand, for example:
"But it still lacks support for the new python 13-14 syntax", or
"Although, when it comes to lambda functions, it often fails to infer parameter types".

After that, you can start to slowly develop the description of the task by first stating
in one-two sentences how it would solve the given problem. 

### Task

The task is the main part of the plan, so it is crucial that the implementer 
and everyone reading the plan would have a clear, **non-ambiguous** understanding 
of exactly what task is needed to be done, with all of it's main details.

To achieve this, start by a gentle introduction of the area to which this task belongs.
Describe the task gently, start from the level 0. Keep introduction small, and free
from irrelevant details, which are not important to the task. Even though the introduction
should be slow and describe basic concepts, it is not intended for beginners to learn from.
It is needed to synchronize the understanding of terms across all the readers and start to 
hint at the main ideas of the task.

After the general introduction, clearly state the current task at hand, making sure the 
implementer would understand the scope of it. It is important that the implementer will do
not less and **not more** than the task is asking for. The task statement must avoid
implementation details and focus purely on the desired behavior.

Finish this section by stating and explaining in detail all the user-facing changes that 
completing this task must produce.

- If the changes are code-level, i.e. the task is fixing a bug in
  a framework or adding new function to a library. Then the explanation should include
  demo code snippets of using this library or framework demonstrating the code use
  and an expected behavior of the code. Note, that any example-specific details that are
  not required must be explicitly marked as illustrative.
- If the changes are UI oriented, then just explain how the new UI and behavior of the
  product should change.

Make sure to highlight all the small, but important details for each of the user-facing 
changes. There must be **no ambiguities** in the task requirements. 

#### Notes

If there are some details of the task, which you want to explicitly stress out, 
or they just do not fit as user-facing changes, you can add them here, in this separate section.

## Task introduction review notes

In the ordered sequence of review passes, i.e. `- **Pass 1**: ...`, `- **Pass 2**: ...`
list changes to the plan that you've made during successive reviews. This
section is needed to avoid making the same mistakes twice by clearly marking
some pieces as incorrect. This section can also be added after the second, task
implementation and testing part of the plan. You can also add new review passes
to these sections after fixing my comments if I write any.

---------------------------------------------------------------------------------

This was the task specification part of the plan.
After you've done it, make sure to carefully review it several times
as written above. Then save it to the
`plans/<plan name>.md` for me to review. I might add some comments
or edit it manually. In any case only when I explicitly approve it
you can start making the second part of the plan based on this first
one (append it to the same file).

---------------------------------------------------------------------------------

## Implementation

The implementation almost universally assumes working with the project code.

The more detailed the plan is, the more it can specify exactly in what file, 
what changes need to be made. And this is precisely what we want in this section.
The detailed specification of everything.
We want to make implementor's job feel completely dull and uncreative when he will
follow this plan. Because it already though through everything for him. But his
job will actually still be meaningful, because for sure no matter how hard you try 
we're still going to miss some unexpected issues which are only going to be revealed
when the actual code will be written.

The implementation section should have a hierarchical structure.
State the list of big implementation goals first, and then detail each of them 
in its own subsection by specifying exactly in what file, what changes need to be made.
Some goals may be too big to specify file-wise changes right away, in that case, split
them up recursively into more basic goals and only then specify the changes by file.

During the explanation of the implementation, you can freely 
use some code/pseudocode snippets, which would schematically demonstrate
what implementation is needed.
You can also quote already existing code and give links to files, documents, urls or
anything which would be useful to implementer for completing that part of the implementation.

## Testing

This is the last, but definitely not the least part of the plan. There are many
nuances which can arise when writing tests. First of which is usually how exactly 
to test the things. You must ask the user to resolve any ambiguities concerning
testing procedures and then generate a list of test cases you are going to add.

For each test case, write exactly what property is it going to test. List the
cases file-wise. If some aspects of the task or implementation require adding 
some non-trivial changes to test them, specify these changes here as well. For
example adding a mock subclass for the networking class is a non-trivial change.

Do not add test instructions that duplicate the ones stated in the other rules.

## Review notes

In the ordered sequence of review passes, i.e. `Pass 1: ...`, `Pass 2: ...`
list changes to the plan that you've made during reviews. This
section is needed to avoid making the same mistakes twice by clearly marking
some pieces as incorrect. This section can also be added after the first, task
specification part of the plan. You can also add new review passes
to these sections after fixing my comments if I write any.

-------------------------------------------------------------

I will repeat the most IMPORTANT things you must always keep in mind again:
1. The plan is split into two parts: task specification part and an implementation plan part.
    The second part depends on the first. Work on them is done separately, 
    I review the task specification part first and then give you permission to start working 
    on the implementation plan part.
2. **Always** review your work several times.
3. **DO NOT** skip details, you don't know who the implementer will be.
4. Keep explanations informative, concise and, most importantly, **unambiguous**.

-----------------------------------------------------------------------------------------

What follows is a full example of some old plan to add a jupyter notebook integration.
Note, that this plan has already been implemented, so the file contents mentioned
in the plan have changed since then and is not relevant to the example anymore.
So the example is purely illustrative, not tied to the concrete code files.

-----------------------------------------------------------------------------------------

# Jupyter Notebook Integration

## Summary

Our dsl framework now can send requests to the agents when run as a python script program,
but this limits interactivity between the user and the agent. The user needs to be able to
conveniently write to an agent and interact with it. The whole idea of jupyter notebooks was
to bring more interactivity to python. The notebooks provide a lot of tools we can reuse for
creating an interactive agent workflows. This plan focuses on two things: a notebook-level
persistent message session with the agent, so that the agent is aware of the messages
sent to it in the previous cell executions, and an interactive agent output UI by utilizing
the jupyter's ability to render arbitrary html inside the cell outputs.
Tests of the correct implementation must include:
- state persistence checks across multiple cell executions 
- appropriate widgets gets drawn in a cell's output

## Introduction

### Prerequisites

- **Documentation**: 
  - [General architecture](ARCHITECTURE.md)
  - [General plan](IMPLEMENTATION_PLAN.md)
  - [OpenHands SDK docs](https://docs.openhands.dev/sdk)
- **Related code**:
  - [Request definition](pyflow/request.py)
  - [Request examples](tests/test_request_dsl.py)
  - [Agent definition](pyflow/agent.py)

### Problem

Currently the framework already provides an ability to compose and run
augmented agent requests as python scripts using the operator DSL language.
But running a script does not allow the user to interactively write new requests
for the same conversation.

This ability can be implemented elegantly using the Jupyter Notebook infrastructure.

### Task

A jupyter notebook consists of a mix of markdown and code cells. Special programs,
called notebook kernels (typically the `ipython` kernel) can run code in these 
cells and the results are outputted right below the cell being run. Kernels also persist 
the global state (variable values, defined functions, etc.) of the notebook across the runs.

Additionally, the cell output in jupyter can be render as html.

Additionally, libraries like `ipywidgets` allow to draw interactive UI elements
in the outputs of code cells and, in general, almost arbitrary html can be rendered there.
On top of that, jupyter provides many utilities[^1], that could in the future be useful for
creating a nice jupyter-native workflow for managing the agents.

The current focus is on the basic integration of our request framework into the jupyter
infrastructure. So that in the future many convenient utilities can be built on top
of it. The completion of this task should produce two mostly independent user-facing features:

#### 1. Interactive cell output with buttons and text fields to interact with the agent.

When the user sends his request to the model by executing the cell, it's output should 
start printing the agent reasoning summaries, tool uses and so on. 
- When the agent wants the user to approve or deny the tool usage, 
    the Approve and Deny buttons should be drawn, as well as the tool name
    and it's invocation parameters just like in any cli agent.
- When the agent wants to give the user a choice of what to do next, the
    buttons for each choice must be drawn vertically 

For example:
```python
# %%
from pyflow import Model, Agent
model = ... # set up the model
agent = Agent(model) # set up some agent
"Add a new level to the game" >> agent
## Output schema:
Thinking...
    The user wants to create add a new level to his game, let
    me check the project

Read 
    game_engine.py
    levels/01_level.json

Thinking...
    Let me ask the details from the user

Question: How hard do you want this new level to be?
1. Medium (Recommended)  [Choose]          
2. Hard                  [Choose]          
3. Easy                  [Choose]          
4. Other: [Input Field]  [Choose]          

You chose: 1. Medium

The agent wants to make the following patch: [Approve] [Deny]
levels/09_level.json
+ {
+   "monsters": ...
+ },
+ ...
```

#### 2. Allow the user to continue the conversation in subsequent code cells.

Once the agent has finished the request in one cell. The user would be able to send
another request, continuing the current conversation in the next cell. For example:

```python
# %%
... # set up an agent, root is a project root folder representation
"Suggest some architecture refactorings for this project" >> agent
# Output schema:
...
1. Apply a visitor design pattern
2. Split the `Parser` class into smaller classes
3. Merge different util classes

## %%
"Ok, let's start by creating some visitor classes" >> agent
# Output schema:
...
```

The message in the second cell is appended to the same conversation, as the first one. So
the agent is in the context of what he is doing. No explicit conversation passing via a variable
is required. Also note, that for now, there must be only one global conversation per notebook.
The user may either explicitly provide the conversation via `"some prompt" >> conversation` or
continue the global conversation via `"some prompt" >> agent`. To create a new global
conversation and delete an old one, he can do `pyflow.clear_notebook_conversation()` or
restart the kernel.

[^1]: Custom line `%` and cell `%%` magics, cell ast transformers, output
    history variables, and custom extensions seems to be the most relevant ones.
    But integration with them are not in the scope of this plan. These are the future
    prospects.

-----------------------------------------------------------------------------------------

This is where you stop and give me this task specification for review. 
If I tell you that it is ok, then you proceed with the implementation and testing plans:

-----------------------------------------------------------------------------------------

## Implementation

The whole implementation process can be split into three parts:

1. Detect notebook execution and route agent runs through notebook session logic.
2. Render notebook-friendly interactive `Session` cell output containing conversation events.
3. Store and retrieve the global conversation state from the jupyter kernel, and append
    this conversation to the user request when appropriate.

### 1. Detect notebook execution and manage global session state

Notebook support is listed as a project priority, but the current runtime has no notebook-specific branching yet.  

#### New file: `pyflow/notebook.py`

Add focused helpers:

- `is_notebook_runtime() -> bool`
- `get_notebook_session() -> NotebookSession | None`
- `set_notebook_session(session: NotebookSession | None) -> None`
- `clear_notebook_conversation() -> None`

The implementation should use private module globals, not low-level kernel APIs. For this task, notebook persistence depends on the Python process remaining alive, which is already how Jupyter kernels work.

#### File: `pyflow/agent.py`

Inside `Agent.__rrshift__`:

- if not in notebook runtime, preserve current behavior exactly
- if in notebook runtime:
    * if no global notebook session exists, create one and store it globally
    * if a global notebook session exists for the same agent instance, append to it
    * if a global notebook session exists for a different agent instance, raise a clear error telling the user 
        to call `pyflow.clear_notebook_conversation()` first

This last rule is important to avoid silently reusing a session with a different model/tools/workspace.

#### File: `pyflow/__init__.py`

Export:

* `clear_notebook_conversation`
* optionally `get_notebook_session` if you want it public

This makes the API mentioned in the example real. Right now it is not exported. 

### 2. Render notebook UI from conversation events

The current repo already uses OpenHands conversations and tests inspect conversation events, so the notebook renderer should be built around those runtime events rather than raw text scraping. 

#### New file: `pyflow/notebook_rendering.py`

Add a renderer layer that maps conversation state into notebook UI.

It should provide:

* `render_notebook_updates(session: NotebookSession) -> None`
* internal helpers to render:

  * reasoning summaries
  * tool invocations
  * approval requests
  * user choices

The renderer should use `ipywidgets` where interaction is required, and plain rich HTML / display output for static transcript items.

The renderer must operate incrementally:

* only render new events since `last_rendered_event_index`
* update `last_rendered_event_index` after successful rendering

This avoids redrawing the entire conversation transcript on every cell execution.

#### Rendering requirements

* Reasoning summaries should be shown as simple transcript blocks.
* Tool invocations must show tool name and arguments.
* Approval states must render Approve and Deny buttons.
* Choice states must render one button per option in vertical order.
* Free-form “Other” choices may render a text box plus button.
* Token-by-token streaming is **not** required.
* Event-by-event progressive rendering **is** required.

If OpenHands does not already expose all required interactive states, then the pyflow adapter layer must translate whatever runtime signal exists into a renderer-specific state object before rendering.

### 3. Preserve existing runtime semantics outside notebooks

This task must not regress the existing scripting path, which is the current supported mode of the framework. The repo’s present design is still script-first and returns OpenHands conversations from request execution.  

#### File: `pyflow/agent.py`

Keep the existing non-notebook path intact:

* fresh conversation per call
* send rendered message once
* run conversation
* return raw `BaseConversation`

Notebook behavior must be a conditional extension, not a replacement.

#### File: documentation

Update README or implementation docs with a notebook usage example showing:

* first cell starts the session
* second cell continues it
* clearing resets the session

Example:

```python
from pyflow import Agent, clear_notebook_conversation

session = "Suggest some refactorings" >> agent
"Start with the parser split" >> session

clear_notebook_conversation()
```

This explicit `session` form is clearer than relying only on implicit global continuation.

---

## Testing

Tests should be added in three groups:

1. runtime behavior tests
2. global notebook state tests
3. renderer tests

The repo already uses `pytest`, snapshot fixtures, offline `TestModel`, and event inspection in tests. Those patterns should be reused here.   

### File: `tests/test_notebook_runtime.py`

#### Test case: non-notebook execution remains unchanged

Property:

* outside notebook detection, `"prompt" >> agent` returns raw `BaseConversation`
* each call creates a fresh conversation

#### Test case: first notebook execution creates session handle

Property:

* inside notebook detection, `"prompt" >> agent` returns `NotebookSession`
* the session contains one underlying OpenHands conversation
* the global notebook session is set

#### Test case: second request through same agent appends to same session

Property:

* `"first" >> agent`, then `"second" >> agent`
* both requests use the same underlying OpenHands conversation object
* the second request is appended, not started from scratch

#### Test case: explicit session continuation works

Property:

* `session = "first" >> agent`
* `"second" >> session`
* the same underlying conversation is reused

#### Test case: different agent with existing global session fails clearly

Property:

* after creating a global notebook session with one agent,
* sending a request through another agent raises a deterministic error
* the message instructs the user to clear the notebook conversation first

#### Test case: clearing removes notebook session

Property:

* after `clear_notebook_conversation()`,
* the global session becomes `None`
* a new request through `agent` creates a fresh notebook session

### File: `tests/test_notebook_rendering.py`

#### Test case: renderer consumes only newly added events

Property:

* if `last_rendered_event_index` points to an earlier boundary,
* renderer processes only later events
* index is advanced after rendering

#### Test case: tool invocation renders tool name and arguments

Property:

* a tool event produces the expected widget/view model structure

#### Test case: approval request renders approve/deny controls

Property:

* approval state produces exactly two buttons
* button callbacks call the correct continuation path

#### Test case: multiple-choice question renders vertical choices

Property:

* options are rendered in the original order
* recommended option label is preserved if present

#### Test case: reasoning summary renders as transcript block

Property:

* summary text is rendered without interactive controls
* multiline content is preserved

These tests do not need a real Jupyter frontend. They should validate the Python-side widget structure or an intermediate renderer data model.

### File: `tests/test_public_api.py` or extend existing public API tests

#### Test case: notebook lifecycle helpers are exported

Property:

* `clear_notebook_conversation` is importable from `pyflow`

#### Test case: notebook result typing is accepted by sinks

Property:

* widened request result types type-check correctly

### Type checking

Run:

```bash
.venv/bin/pyright
```

This is especially important because the task changes sink/result typing and introduces a new reusable runtime object. The project conventions already require pyright after Python changes. 

### Optional manual smoke test

A short manual notebook smoke test may be useful:

1. start a notebook
2. create an agent
3. run one prompt
4. continue in next cell
5. clear conversation
6. run again and verify fresh state

This is optional and should not replace automated pytest coverage.

## Implementation review notes

* Reframed notebook persistence as a **new runtime mode**, not as existing behavior.
* Replaced vague “kernel state” wording with a concrete module-global session approach.
* Added a required **notebook session handle** because raw `BaseConversation` is not enough for `"prompt" >> conversation`.
* Added explicit behavior for the ambiguous “second agent while global session exists” case.
* Limited the rendering requirement to **event-level progressive updates**, avoiding token-level ambiguity.
* Marked `clear_notebook_conversation()` as a new public API that must be added, not assumed.
