from langgraph.prebuilt import create_supervisor
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# Agent imports
from agents.cloud_ops_agent import CloudOpsAgent
from agents.sysadmin_agent import SysAdminAgent
from agents.fallback_agent import FallbackAgent

# Initialize Gemini
gemini = ChatGoogleGenerativeAI(model="gemini-pro")

# 🔁 Dynamic LLM-based routing logic
def route_agent(state: dict) -> str:
    prompt = f"""
You are a routing agent in a root cause troubleshooting system.

Your job is to decide which specialized agent should handle the user's issue based on:
- User dialog
- Final problem statement
- Flow type (guided/non-guided)
- Documentation (generated from intent agent)

Agents available:
- cloud_ops_agent → for cloud operation & API planning (AWS/GCP/Azure)
- sysadmin_agent → for SSH, login, or host-level troubleshooting
- fallback_agent → for generic issues that can't generate a plan

Only respond with one of the following values:
cloud_ops_agent, sysadmin_agent, fallback_agent

---

Dialog:
{state.get("dialog")}

Final Problem Statement:
{state.get("final_problem_statement")}

Flow Type:
{state.get("flow_type")}

Documentation:
{state.get("documentation")}

What agent should handle this?
"""

    response = gemini.invoke([HumanMessage(content=prompt)])
    selection = response.content.strip().lower()

    # Ensure valid result
    if selection not in ["cloud_ops_agent", "sysadmin_agent", "fallback_agent"]:
        return "fallback_agent"

    return selection


# ✅ Build LangGraph Supervisor Agent
def build_supervisor_agent():
    return create_supervisor(
        agents={
            "cloud_ops_agent": CloudOpsAgent(),
            "sysadmin_agent": SysAdminAgent(),
            "fallback_agent": FallbackAgent(),
        },
        select_next=route_agent,
    )
