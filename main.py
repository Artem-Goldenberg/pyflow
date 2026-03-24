import os

from openhands.sdk import LLM, Agent as OHAgent, Conversation, Tool
from pydantic import SecretStr
# from openhands.tools import TerminalTool, FileEditorTool
from pyflow import Agent, Model, install_rich_pretty

from pyflow.model_generator import discover_provider_models, generate_models_file, generate_models_from_provider

from dotenv import load_dotenv
load_dotenv()

install_rich_pretty()

from pyflow.gittools import GitRepo

repo = GitRepo.open(".")

worktree = repo.create_worktree(".worktree/")

repo.remove_worktree()


# model = Model.subscription()

# agent = Agent(model=model)

# print(os.environ["GROQ_API_KEY"])

# generate_models_from_provider(
#     provider_name="groq",
#     base_url="https://api.groq.com/openai/v1",
#     api_key=SecretStr(os.environ["GROQ_API_KEY"]),
# )

# from pyflow._generated.models import Models

# Models.groq.gpt.oss_b120()

"""
Plan:
- Fix empty output in jupyter
- 
"""

# from pyflow._generated.models import Models

# Models.groq.allam.

"""
curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/v1/models
"""



# model = AIModel(
#     name="groq/qwen/qwen3-32b",
#     api_key=SecretStr(os.environ["GROQ_API_KEY"]),
#     max_input_tokens=32768,
#     max_output_tokens=8192,
# )

# agent = Agent(model=model)

# from openhands.sdk.context import Skill

# def skills(*names: str) -> list[Skill]:
#     ...

# my_skill_obj: Skill = ...

# agent @= skills(".agents", "path/to/skill-folder", my_skill_obj) @ tools("terminal", "read_file")




# session = "Hi" >> agent

# print("The session was")
# print("===============================")
# print(session)
