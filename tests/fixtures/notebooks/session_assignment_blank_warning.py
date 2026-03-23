# pyright: reportUnusedExpression=false
# %%
import logging

from openhands.sdk import Message, TextContent
from openhands.sdk.llm import MessageToolCall

from pyflow import Agent, Model

model = Model.test(
    scripted_responses=(
        Message(
            role="assistant",
            content=[TextContent(text="")],
            tool_calls=[
                MessageToolCall(
                    id="done",
                    name="finish",
                    arguments='{"message": "Done"}',
                    origin="completion",
                )
            ],
        ),
    )
)
agent = Agent(model=model, tools=())

# %%
session = "Hi" >> agent
logging.getLogger("openhands").warning("   ")
