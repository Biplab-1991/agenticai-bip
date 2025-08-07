from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal, Dict, Any
from langgraph.graph import StateGraph, create_supervisor
from langgraph.prebuilt import create_agent
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
import os

# --- Step 1: Define BaseModels ---

class SupervisorInput(BaseModel):
    input: str
    route_to: Literal["cloud_ops", "sysadmin"]  # Optional routing hint


class SupervisorOutput(BaseModel):
    result: str
    agent_used: str
    metadata: Dict[str, Any] = {}


# --- Step 2: Dummy Tools for Each Agent ---

@tool
def cloud_ops_tool(query: str) -> str:
    return f"[CloudOps] Handled query: {query}"

@tool
def sysadmin_tool(query: str) -> str:
    return f"[SysAdmin] Resolved issue: {query}"


# --- Step 3: LLM and Agent Setup ---

llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=os.environ["GOOGLE_API_KEY"])

cloud_ops_runnable = create_agent(llm, tools=[cloud_ops_tool], agent_type="openai-tools")
sysadmin_runnable = create_agent(llm, tools=[sysadmin_tool], agent_type="openai-tools")

supervisor = create_supervisor(
    llm,
    agents={
        "cloud_ops": cloud_ops_runnable,
        "sysadmin": sysadmin_runnable,
    },
    agent_type="openai-tools",
)

# --- Step 4: LangGraph with Supervisor Routing ---
graph = StateGraph(supervisor.input_type)
graph.add_node("supervisor", supervisor)
graph.set_entry_point("supervisor")
graph.set_finish_point("supervisor")
supervisor_runnable = graph.compile()

# --- Step 5: FastAPI App with Routes ---
app = FastAPI()


@app.post("/supervisor", response_model=SupervisorOutput)
async def handle_supervisor(payload: SupervisorInput):
    response = await supervisor_runnable.ainvoke(payload.dict())
    return SupervisorOutput(
        result=response.get("output", ""),
        agent_used=response.get("agent", ""),
        metadata=response.get("intermediate_steps", {})
    )


@app.post("/cloud_ops")
async def handle_cloud_ops(payload: SupervisorInput):
    response = await cloud_ops_runnable.ainvoke(payload.dict())
    return {"result": response.get("output", ""), "agent": "cloud_ops"}


@app.post("/sysadmin")
async def handle_sysadmin(payload: SupervisorInput):
    response = await sysadmin_runnable.ainvoke(payload.dict())
    return {"result": response.get("output", ""), "agent": "sysadmin"}
