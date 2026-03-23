import os

from openhands.sdk import LLM, Agent as OHAgent, Conversation, Tool
from pydantic import SecretStr
# from openhands.tools import TerminalTool, FileEditorTool
from pyflow import Agent, Model, install_rich_pretty
from dotenv import load_dotenv
# load_dotenv()

install_rich_pretty()

model = Model.subscription()

# model = AIModel(
#     name="groq/qwen/qwen3-32b",
#     api_key=SecretStr(os.environ["GROQ_API_KEY"]),
#     max_input_tokens=32768,
#     max_output_tokens=8192,
# )

agent = Agent(model=model)

# from openhands.sdk.context import Skill

# def skills(*names: str) -> list[Skill]:
#     ...

# my_skill_obj: Skill = ...

# agent @= skills(".agents", "path/to/skill-folder", my_skill_obj) @ tools("terminal", "read_file")




# session = "Hi" >> agent

# print("The session was")
# print("===============================")
# print(session)

