from datetime import datetime
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from typing import TypedDict, List, Literal

# ---------- 1. Define Shared State ----------
class AgentState(TypedDict):
    messages: List[BaseMessage]
    agent_status: Literal["date_agent", "weather_agent", "done"]
    date: str
    weather: str

# ---------- 2. Agent 1: Get Date ----------
def date_agent(state: AgentState) -> AgentState:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        **state,
        "date": today,
        "agent_status": "weather_agent"
    }

# ---------- 3. Agent 2: Get Weather ----------
def weather_agent(state: AgentState) -> AgentState:
    date = state["date"]
    weather = f"The weather on {date} is Sunny with clear skies."
    return {
        **state,
        "weather": weather,
        "agent_status": "done"
    }

# ---------- 4. Supervisor ----------
def supervisor(state: AgentState) -> str:
    if state["agent_status"] == "date_agent":
        return "date_agent"
    elif state["agent_status"] == "weather_agent":
        return "weather_agent"
    else:
        return END

# ---------- 5. Build LangGraph ----------
graph = StateGraph(AgentState)
graph.add_node("date_agent", date_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_conditional_edges("date_agent", supervisor)
graph.add_conditional_edges("weather_agent", supervisor)
graph.set_entry_point("date_agent")
graph_executor = graph.compile()

# ---------- 6. Run the Workflow ----------
initial_state: AgentState = {
    "messages": [],
    "agent_status": "date_agent",
    "date": "",
    "weather": ""
}
final_state = graph_executor.invoke(initial_state)

# ---------- 7. Output Only Weather ----------
print(final_state["weather"]) 