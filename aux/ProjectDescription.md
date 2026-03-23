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


Ok, so, here are my thoughts after reading through all of these frameworks and whatnot. 
- PydanticAI
    As I understand, it just add a layer between the model and my code which validates
    that the model returned the correctly structured results, and if not it somehow
    prompts the model again or does something like that. And it also allows for quick tool 
    addition as a python function via the decorator. If this is all they bring to the table,
    then I'm not interested, his bit of functionality I feel is completely not needed for me 
    right now, maybe later when we will want to refine the model responses, then we might
    use it, yes. + They enforce their own approach of defining tools and I'm not impressed with it.

- CrewAI
    Too high-level, too general framework for a simple coding agent. All this task creation
    and crew management is just too heavy + I don't think you can get much control over all 
    of this.

- ClaudeCode SDK
    Heavily dependant on a claude model. Which is a shame because their abstractions doesn't
    seem very bad at all. They even implement asyncronous functions. But we need control of
    models, we don't want to hack it. The authors definitely didn't think that this SDK 
    would be used to something which is not claude code related. 

- OpenAI SDK
    Didn't do a lot of research on this one. But it seems to be just some small helper 
    to build a lot of general purpose agents. Which is not what I want. I want a single
    but flexible and robust and inspectable coding agent.

- OpenHands SDK
    

- LangChain and LangGraph
    The words "production ready" literally scream out of these family of libraries. There
    are things I like in them, for example for some reason I like their approach to have
    different packages for handling llms from different providers. For some reason I don't
    really like this approach much more thean the litellm thing, I don't know why, just 
    litellm forces you to use their format, to convert to their classes and names and
    so on (I know it's really an openai format, but still, the names are theirs and I don't like).

    So this bit I like, but a lot of other stuff I don't. For example all of this really, 
    pure production, anti science and anti-beauty architecture, that everything is mutable,
    you create your PosgressSavers and InMemorySavers to persist everything, this is flexible
    this is yes, much more general and flexible than immutable state (perhaps), but ugly, no
    room for beauty there.

    LangChain agents is a library on top of the whole langchain core infrastructure and also
    on top of the langgraph infrastructure, where you define an execution graph which your
    agent follows. This single idea is good, but then they immediately productionaze it by
    just creating a bunch of weird nodes and all this middleware, the only work middleware,
    that's it like, you know it's already going to be a pure production thing.

- DeepAgents
    Even higher abstraction over the LangChain agents (I think) at which point this is
    definetly way to big of an abstraction for the amount of control I want from the
    library. 

- OpenHands SDK
    The thing which I will actually use for now! It seems to be quite high level, so it
    provides a lot of things out of the box, but also it seems to give just enough control
    so that it would satisfy me. At least for now, when I need to make a prototype. Later
    we can of course consider switching to some small lang chain components or, what I
    would like most out of it all, is to just write all these things myself. Using only
    an absraction over models (or even just openai protocol). Yes, this is quite a lot of
    work actually, but it's very much doable especially with the agents. So yeah. But for
    now, again, this OpenHands SDK, it's clearly, wait... who said it? Who said that something's
    made iwth love? Ohh yeah, they've said it about zed, well this framework is also very like
    it's very beautiful. Just like these abstractions, they are clean. No really, they are
    completely different from lang chain ones. Lang chain ones are dirty, but fitting for
    any pupose. These ones only fit for the particular purpose of this framework to allow for
    bulding coding agents. But it's clean, no hacks. Everything just made right. So I choose this.
    Won't even look at langchain at this point. It's 5 20! I soo need to sleep. Ok, well.
    I am not going to get much sleep today.
