# pyright: reportUnusedExpression=false
# %%
from pyflow import Agent, Model
from openhands.sdk.llm import Message, MessageToolCall, TextContent

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
"Hi" >> agent
