from langgraph_supervisor import create_supervisor
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph

from agents.cloud_ops_agent import CloudOpsAgent
from agents.sysadmin_agent import SysAdminAgent
from agents.fallback_agent import FallbackAgent

# Gemini LLM
gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-05-20",
    google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"
)

# Dynamic prompt builder
def routing_prompt(state: dict) -> str:
    return f"""
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

# ✅ Build the Supervisor Agent inside a LangGraph StateGraph
def build_supervisor_agent():
    # Create routing supervisor node
    supervisor_graph = create_supervisor(
        agents=[
            CloudOpsAgent(),
            SysAdminAgent(),
            FallbackAgent()
        ],
        model=gemini,
        prompt=routing_prompt,  # 🧠 function-based prompt
        supervisor_name="supervisor_agent"
    )

    # Wrap inside a LangGraph StateGraph to capture __steps__
    builder = StateGraph(dict)
    builder.add_node("agent", supervisor_graph.compile())
    builder.set_entry_point("agent")
    builder.set_finish_point("agent")
    return builder.compile()
