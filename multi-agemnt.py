import os
from typing import TypedDict

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_agent
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

# -------- Load env vars --------
load_dotenv()

# -------- LangGraph State --------
class AgentState(TypedDict):
    input: str
    output: str

# -------- Agent 1 Node --------
def agent_one(state: AgentState) -> AgentState:
    @tool
    def fake_tool_one(text: str) -> str:
        """A dummy tool that echoes input."""
        return f"Agent 1 received: {text}"

    llm = ChatGoogleGenerativeAI(
        model="gemini-pro",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.2,
    )
    tools = [fake_tool_one]
    agent = create_agent(llm, tools, agent_type="openai-tools")

    result = agent.invoke(state["input"])
    return {**state, "output": str(result)}

# -------- Agent 2 Node --------
def agent_two(state: AgentState) -> AgentState:
    @tool
    def fake_tool_two(text: str) -> str:
        """A dummy tool that returns confirmation."""
        return f"Agent 2 processed: {text}"

    llm = ChatGoogleGenerativeAI(
        model="gemini-pro",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.2,
    )
    tools = [fake_tool_two]
    agent = create_agent(llm, tools, agent_type="openai-tools")

    result = agent.invoke(state["output"])  # Pass output from agent_one
    return {**state, "output": str(result)}

# -------- Build Graph --------
def build_multi_agent_graph():
    builder = StateGraph(AgentState)

    builder.add_node("agent1", agent_one)
    builder.add_node("agent2", agent_two)

    builder.set_entry_point("agent1")
    builder.add_edge("agent1", "agent2")
    builder.add_edge("agent2", END)

    return builder.compile()

# -------- FastAPI Setup --------
app = FastAPI(title="LangGraph Multi-Agent API")
workflow = build_multi_agent_graph()

class InputPayload(BaseModel):
    message: str

@app.post("/run")
def run_workflow(payload: InputPayload):
    state = {"input": payload.message, "output": ""}
    result = workflow.invoke(state)
    return {"final_output": result["output"]}
