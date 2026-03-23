---
name: planning
description: "Create or improve a three-stage reviewed plan for a single non-trivial engineering task: first write the task-specification part and stop for approval, then write the implementation and testing part. Use when asked to make a plan, edit an existing plan or plan section, or continue from a user-provided approved first part. Do not use for trivial edits, broad brainstorming, or immediate coding requests."
user-invocable: true
---

When asked to make a plan for solving an issue, split it in three parts:
1. summary and task specification part
2. implementation part 
3. testing part

If there are several unrelated problems to solve, then ask which one to make a plan for first,
**DO NOT** try to put them all in one plan together, need to pick one!

After you've created and carefully reviewed the first part stop, and send it to me.
I can make comments or edit it manually, I can even start a session by pasting
finished first parts of the plan and ask you to improve it or to straight away write 
the next part based on the provided ones.
The same applies to each next part, after you've created  and carefully reviewed it 
based on the previous parts, give it to me for review. We can iterate on it for a while,
and once I told you it is ok, we can move on to the next part, until I ask you to go and 
actually implement the full plan.
Or again, I can start the session by giving you a finished plan and ask you to 
implement it right away.

Next, I will give you general instructions concerning the plan construction.
All the general instructions I'm about to give you apply to each part of the plan.

When producing each part of the plan keep in mind the following things:
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
    your incremental review improvements at the end of current part.

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

Now I will describe the precise format for the each part of the plan:

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

### Review notes

In the ordered sequence of review iterations, i.e. `1. ...`, `2. ...`,
list the concrete changes you made during successive reviews. This section helps
avoid repeating the same mistakes by clearly recording what was corrected or
clarified. This section can also be added after each part of the plan.
You can also append new review items here after fixing my comments if I write any.
Do not change the old review items unless explicitly asked, 
they stay as a history log and are important.

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
what implementation is needed. In this section, code snippets are even more
preferable than textual description. Use it to simplify the expression of intent.
You can also quote already existing code and give links to files, documents, urls or
anything which would be useful to implementer for completing that part of the implementation.

### Review notes

Again, same as before, append the review notes to this part, 
either your own ones that you did during the self-review
or my comments if I leave some. 
Do not delete the old notes unless explicitly asked, only append new ones.

---------------------------------------------------------------------------------

And this was the implementation part of the plan. Again, after it's done tell the
user to review it. This is where you'll probably spend the longest time iterating
and improving this part. When the user approves, move on to the next part.

---------------------------------------------------------------------------------

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

### Review notes

And again, for the third time log the review notes if there are any. For the
testing part there shouldn't be too many of them.

---------------------------------------------------------------------------------

I will repeat the most IMPORTANT things you must always keep in mind again:
1. The plan is split into two parts: task specification part and an implementation plan part.
    The second part depends on the first. Work on them is done separately, 
    I review the task specification part first and then give you permission to start working 
    on the implementation plan part.
2. **Always** review your work several times.
3. **DO NOT** skip details, you don't know who the implementer will be.
4. Keep explanations informative, concise and, most importantly, **unambiguous**.

-----------------------------------------------------------------------------------------

What follows is a full illustrative example of an old plan to add a jupyter notebook integration.
This example demonstrates the expected structure, level of detail, and wording style of the plan.
Its file paths, API names, and code snippets are illustrative. They may describe files that have
since changed, moved, or do not exist in the current repository. The example exists only to show how the plan should be written.

-----------------------------------------------------------------------------------------

# Jupyter Notebook Integration

## Summary

Our request DSL already works well in regular Python scripts, but that workflow is not interactive
enough for notebook use. This task adds notebook-oriented conversation continuity and inline
interactive outputs, while keeping the existing script behavior unchanged. After implementation,
testing must confirm state persistence across cell executions, correct interactive rendering, and
no regressions in the non-notebook execution path.

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

Currently, our request DSL can already send prompts to an agent and run them successfully from
Python scripts.

But it still does not provide a notebook-native workflow in which the user can continue the same
conversation in later cells and respond to agent interaction requests directly in the output area.

This task solves that gap by introducing notebook session handling and notebook-friendly rendering,
without changing the existing script-first behavior outside notebooks.

### Task

A jupyter notebook keeps Python state across cell runs and can render rich outputs below each cell.
This makes it a good environment for an interactive agent workflow, provided that the framework
can preserve conversation state and display interactive controls inside the cell output.

The task is to extend the current request framework with notebook-specific behavior for exactly two
user-facing capabilities. The scope is limited to notebook conversation continuity and notebook
output rendering. It does **not** include broader notebook integrations such as custom magics,
history tooling, or extension APIs.

#### 1. Interactive cell output with buttons and text fields to interact with the agent

When the user sends a request from a notebook cell, the output should render a readable event stream
for that run, including reasoning summaries, tool usage, and interactive controls when the agent
needs input.

For example:

```python
# %%
from pyflow import Model, Agent

model = ...  # illustrative setup
agent = Agent(model)

"Add a new level to the game" >> agent
# Illustrative output shape:
# Thinking...
# Read game_engine.py
# Read levels/01_level.json
# Question: How hard should the level be?
# 1. Medium (Recommended) [Choose]
# 2. Hard [Choose]
# 3. Easy [Choose]
# 4. Other: [Input Field] [Choose]
#
# The agent wants to patch levels/09_level.json [Approve] [Deny]
```

Expected behavior:

- reasoning summaries are shown as transcript-like blocks
- tool usage is shown with the tool name and invocation parameters
- if approval is needed, `Approve` and `Deny` controls are rendered
- if a choice is needed, options are rendered vertically
- file names such as `game_engine.py`, `levels/01_level.json`, and `levels/09_level.json` are illustrative only

#### 2. Allow the user to continue the conversation in subsequent code cells

After one notebook cell finishes, the user must be able to continue the same conversation from a
later cell without manually reconstructing prior context.

Illustrative example:

```python
# %%
"Suggest some architecture refactorings for this project" >> agent

# %%
"Ok, start with the parser split" >> agent
```

Expected behavior:

- the second prompt is appended to the same notebook conversation as the first one
- no explicit conversation variable is required for the implicit notebook flow
- for now, there is only one global conversation per notebook
- the user may still continue explicitly via `"some prompt" >> conversation`
- the user may reset the notebook-global conversation with
  `pyflow.clear_notebook_conversation()` or by restarting the kernel

#### Notes

- The examples above are illustrative and do not constrain the exact UI wording.
- Token-by-token streaming is not required by this task unless separately stated.
- Support for custom `%` / `%%` magics, AST transforms, and similar notebook-specific features is
  out of scope for this task.

### Review notes

1. Narrowed the scope to two concrete notebook-facing capabilities and removed unrelated future
   notebook ideas from the task requirements.
2. Separated current behavior from desired behavior more explicitly, so the implementer can see
   what must remain unchanged.
3. Rewrote the user-facing changes to focus on observable behavior rather than implementation
   details.

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

The whole implementation process can be split into three parts:

1. detect notebook execution and manage notebook conversation state
2. render notebook-friendly interactive outputs from conversation events
3. preserve the current non-notebook runtime behavior exactly

### 1. Detect notebook execution and manage global session state

Notebook support must be added as a conditional runtime mode. The existing non-notebook execution
path must remain the default behavior outside notebooks.

#### New file: `pyflow/notebook.py`

Add focused helpers:

- `is_notebook_runtime() -> bool`
- `get_notebook_session() -> NotebookSession | None`
- `set_notebook_session(session: NotebookSession | None) -> None`
- `clear_notebook_conversation() -> None`

For this task, notebook persistence should rely on module-level state inside the live kernel
process, not on lower-level jupyter kernel APIs.

#### File: `pyflow/agent.py`

Inside `Agent.__rrshift__`:

- if not in notebook runtime, preserve current behavior exactly
- if in notebook runtime:
  - create and store a notebook session when none exists yet
  - append to the existing session when it belongs to the same agent
  - raise a clear error when a different agent tries to reuse the active global session

That error should instruct the user to call `pyflow.clear_notebook_conversation()` first.

#### File: `pyflow/__init__.py`

Export:

- `clear_notebook_conversation`
- optionally `get_notebook_session` if it is meant to be public

These are **new** public API names and must be marked as such in the plan.

### 2. Render notebook UI from conversation events

The notebook renderer should consume structured conversation events rather than scraping text.

#### New file: `pyflow/notebook_rendering.py`

Add a renderer layer that can:

- render reasoning summaries
- render tool invocations
- render approval requests
- render user choices

The renderer should use `ipywidgets` where interaction is needed and plain notebook display output
for static transcript items.

The rendering should be incremental:

- only render events that were not rendered before
- track the last rendered event index on the notebook session
- update that index only after a successful render pass

### 3. Preserve existing runtime semantics outside notebooks

This task extends the framework. It must not replace the current execution model.

#### File: `pyflow/agent.py`

Keep the existing non-notebook path intact:

- fresh conversation per call
- regular request execution flow
- raw `BaseConversation` return value

Notebook behavior is an additional path, not the new default.

#### File: documentation

Update README or implementation docs with a notebook usage example showing:

```python
from pyflow import Agent, clear_notebook_conversation

session = "Suggest some refactorings" >> agent
"Start with the parser split" >> session

clear_notebook_conversation()
```

The concrete variable names are illustrative.

### Review notes

1. Reduced the implementation plan to three major goals so it mirrors the task scope more closely.
2. Marked new public APIs explicitly and removed assumptions that were not visible in the task
   specification part.

---------------------------------------------------------------------------------

The implementation part is done. Again, save it
and let the user review. This part is where you'll likely spend
the longest time iterating and fixing the user comments.

---------------------------------------------------------------------------------

## Testing

Tests should be added in three groups:

1. runtime behavior tests
2. notebook state tests
3. renderer tests

### File: `tests/test_notebook_runtime.py`

#### Test case: non-notebook execution remains unchanged

Property:

- outside notebook detection, `"prompt" >> agent` returns raw `BaseConversation`
- each call creates a fresh conversation

#### Test case: first notebook execution creates a session

Property:

- inside notebook detection, `"prompt" >> agent` returns `NotebookSession`
- the global notebook session is set

#### Test case: second notebook request appends to the same session

Property:

- two sequential prompts through the same agent reuse the same underlying conversation
- the second prompt is appended rather than starting a new conversation

#### Test case: different agent with existing global session fails clearly

Property:

- after one agent creates the notebook-global session, a different agent triggers a deterministic
  error with a clear reset instruction

#### Test case: clearing removes notebook session

Property:

- `clear_notebook_conversation()` removes the stored notebook session
- the next notebook request creates a fresh session

### File: `tests/test_notebook_rendering.py`

#### Test case: renderer consumes only newly added events

Property:

- only events after the saved render boundary are rendered
- the render boundary advances after success

#### Test case: approval request renders approve/deny controls

Property:

- approval state produces exactly two controls
- callbacks continue the correct execution path

#### Test case: multiple-choice question renders choices in order

Property:

- choices preserve their original order
- any recommended marker is preserved if present

#### Test case: reasoning summary renders as a transcript block

Property:

- static reasoning text is rendered without interactive controls
- multiline content is preserved

### File: `tests/test_public_api.py` or extend existing public API tests

#### Test case: notebook lifecycle helpers are exported

Property:

- `clear_notebook_conversation` is importable from `pyflow`

### Optional manual smoke test

1. start a notebook
2. create an agent
3. run one prompt
4. continue in the next cell
5. clear the conversation
6. run again and verify that the conversation is fresh

### Review notes

1. Simplified the testing section so each test case states a concrete property without repeating
   unrelated project conventions.

---------------------------------------------------------------------------------
