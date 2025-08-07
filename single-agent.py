import os
from typing import TypedDict
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_agent

# -------- Load API Key --------
load_dotenv()

# -------- Dummy Tool --------
@tool
def fake_calculator(expression: str) -> str:
    """Evaluates a math expression (returns dummy result)."""
    return f"The result of `{expression}` is 42 (dummy)"

# -------- LangGraph State --------
class AgentState(TypedDict):
    input: str
    output: str

# -------- Node with LLM + Agent inside --------
def run_agent_node(state: AgentState) -> AgentState:
    # Setup inside node (not optimal for production)
    tools = [fake_calculator]
    llm = ChatGoogleGenerativeAI(
        model="gemini-pro",
        temperature=0.2,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )
    agent_runnable = create_agent(llm, tools, agent_type="openai-tools")

    # Run agent
    response = agent_runnable.invoke(state["input"])
    return {
        "input": state["input"],
        "output": str(response)
    }

# -------- LangGraph Definition --------
builder = StateGraph(AgentState)
builder.add_node("agent", run_agent_node)
builder.set_entry_point("agent")
builder.add_edge("agent", END)
graph = builder.compile()

# -------- FastAPI Setup --------
app = FastAPI()

class AgentInput(BaseModel):
    message: str

@app.post("/run-agent")
async def run_agent(input: AgentInput):
    result = graph.invoke({"input": input.message})
    return {"response": result["output"]}
