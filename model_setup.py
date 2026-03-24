import nest_asyncio
from dotenv import load_dotenv

from pyflow import Agent, Model

load_dotenv()
nest_asyncio.apply()

model = Model.subscription()

empty_agent = Agent(model=model, tools=())

agent = Agent(model=model)
default_agent = agent
