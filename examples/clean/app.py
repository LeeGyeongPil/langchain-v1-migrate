"""Already on langchain 1.x: nothing to migrate."""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain.tools import tool
from langchain_core.messages import HumanMessage


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


model = init_chat_model("openai:gpt-4o-mini")
agent = create_agent(model, tools=[add])
print(init_embeddings, HumanMessage(content="hi"))
