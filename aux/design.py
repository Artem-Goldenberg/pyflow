from enum import StrEnum


class Model:
	...


class Provider:
	...

# Somewhere in generated.pyi

class model:
	class openai(Provider):
		GPT52: Model
		Codex: Model

	class anthropic(Provider):
		ClaudeOpus: Model
		ClaudeSonnet: Model


model.provider.id

model.openai.Codex



class Agent:
	"""Something that can use a model in a loop, or once..."""
	tools: list[Tool] = builtin.tools
	context: 


class EventStatistic:
	credits_used: float
	model: Model
	time_to_first_token: float
	response_time: float


class AbstractEvent(ABC):
	stats: EventStatistic


class ToolCall(AbstractEvent):
	...


class Thoughts(AbstractEvent):
	context: MarkdownStream


class Say(AbstractEvent):
	...


class Answer(AbstractEvent):
	...


Event = ToolCall | Thoughts | Say | Answer


class Progress:
	agent: Agent
	nodes: AsyncIterable[Event] # but it is an async stream


class Session:
	answer: Answer
	progress: Progress


# ......................


# The user can add tools either by

class WebSearch(Tool):
	"""
	Allows to do web searches, blah blah blah
	"""

	use_when = "Blah blah blah"

	def run(self, query: str) -> list[URL]:
		...

# Or just with something like

@tool(use_when="Blha blha blha")
def web_search(query: str) -> list[URL]:
	"""Description, blah, blah"""
	...


class Request:
	def __shiftr__(self, some) -> Request:
		...

	def __matmul__(self, attachment) -> Request:
		...


git.commit
jira.ticket


class ToolGroup(Tool):
	...


# Final product:

class git(ToolGroup):

	def commit(self, message: str) -> str: ...

	def diff(self, filename: str | None = None) -> Diff: ...


class jira:
	def ticket(self, num: int) -> WebContent: ...

WebContent = str # for now mock it

# Tool integration:

"""
So, the model wants to call tools, but above all there is also a bash tool
always avaialble for the model to use, so some of the tools can be always 
replaced with calling a bash command, git is the primary example for this.

So the user (and us) might want to try different approaches how would the model
call tools, default integrations:
	- mcp
	- command line tool
	- python function

So for now we can implement those at least
"""

class ToolIntegration:
	"""
	Like we want to control, how to

	"""

	def parse_tool_call(self, response: Iterable[Token]):
		...


class MCP(ToolIntegration):
	def parse_tool_call(self, response: Iterable[Token]):
		json.parse(...)
	
	def invoke(self, tool_func):
		...


class CommandLine(ToolIntegration):
	def parse_tool_call(self, response: Iterable[Token]):
		...
	...


class PythonFunction(ToolIntegration):
	def parse_tool_call(self, response: Iterable[Token]):
		...


"""
So, what, how the process of agent calling a tool will even look like?
"""

model.send(prompt)

response = model.get_response()


result = current_tool_integration.parse_as_tool_call(response)

if result.positive:
	result.invoke()



# Utility functions, mainly to generate python stubs out of
# the content that user provides

# For example if he has a java project

# some.java
#	class Some {
#	     boolean haveBeans() { ... }
#    }
# more.java


# then we need to generate stubs like:

class java:
	class Some:
		haveBeans: ContextItem

	class More:
		...

# And in reality it will be implemented something like:

class Java:
	def __getattr__(self, name):
		file = find_file(f"{name}.java")
		file_ast = java_parse(file)
		return JavaClass(file_ast.find('class'))

class JavaClass:
	def __init__(self, ast: JavaAST): ...
	def __getattr__(self, name):
		item_ast = self.ast.find(name)
		return ContextItem(item_ast)

java = Java()

# Or maybe literally just like

class java:
	class Some:
		_ast = java_parse("some.java")
		haveBeans = ContextItem(_ast.find("haveBeans"))


# Now about the context


class File:
	def tokens() -> Iterable[Token]: 
		...


class Text:
	def tokens() -> Iterable[Token]: 
		...


class Code:
	def tokens() -> Iterable[Token]: 
		...


class Rule:
	def tokens() -> Iterable[Token]: 
		...


ContextPiece = File | Text | Code | Rule


class Context:
	pieces: list[ContextPiece]
	...


#############################

"""
Running environments:
- as a single python executable via `model.run_cli(request)` and `python your_file.py`
- in the python repl: `from pyflow import *` and `"do something" >> model.SomeModel`
- in the jupyter notebook: 
	retains global context,
	run without prompt via `... >> model`
	uses pywidgets or something to draw agent choices and stuff in the cell output,
	can add and edit? cells in the future
- as a server accepting agent requests 
	for the typescript fronted in a vscode extension?
	for the java/kotlin fronted for the intelij idea?
	for the web/mobile applications???

user adds tools, pip installs packages with more tools, or just make wrappers around libraries
user also adds skills and other stuff, sets very customizable permissons on tools

user should also be able to add code to the context, but for now it's only limited to python code!

create reusable agents via attaching permanent tools to models?

	my_python_agent = model.SomeModel @ tools.python
	"Some request" >> my_python_agent

by default model doesn't get any context more than the user provided. But in python code it
can get context from sessions via

	session = "do something to class X" >> model
	session >> "and now review it" >> model  # OR
	"and now review it" @ session >> model

inside the jupyter notebooks the global session should be attached automatically.
inside the notebooks: `pyflow.notebook_session()`

you can attach files yourself. If you don't attach files at all, then the model will be blind,
it cannot possibly know anything. But, it can call builtin tools to list the current directory,
find in what file it is executiong (probably). And then the results all appear inside a session.

Also there is a whole long discussion about tool integrations. But that we will leave for
another time.
"""


"""
On the mcp tools:
For now we won't implement any mcp client support. Perhaps yes, in the
future we will add some function like, add mcp server on this address or 
something like that. Or just put this mcp server into regisry and it will
be run and managed as our application and runtime runs. Perhaps yes. But
for now, no mcp clients. The user just defines his function via @tool.

"""

