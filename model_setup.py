from pyflow import Agent, Model
from dotenv import load_dotenv
load_dotenv()

import nest_asyncio
nest_asyncio.apply()

model = Model.subscription()

empty_agent = Agent(model=model, tools=())

default_agent = Agent(model=model)
