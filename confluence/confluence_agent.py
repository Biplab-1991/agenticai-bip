import os
import requests
from datetime import datetime
import time
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage
from typing import TypedDict, List, Literal
from google.cloud import bigtable

# ---------- 1. Define Shared State ----------
class AgentState(TypedDict):
    messages: List[BaseMessage]
    agent_status: Literal["date_agent", "weather_agent", "confluence_agent", "done"]
    date: str
    weather: str

# ---------- 2. Bigtable Save Function ----------
def save_to_bigtable(date: str, weather: str, duration_ms: int):
    try:
        print(f"[LOG] Connecting to Bigtable: project=verizon-agenticai, instance=weather-instance")
        client = bigtable.Client(project="verizon-agenticai")
        instance = client.instance("weather-instance")
        table = instance.table("weather-table")

        row_key = date.encode()
        bt_row = table.direct_row(row_key)
        bt_row.set_cell("info", "weather", weather)
        bt_row.set_cell("info", "duration_ms", str(duration_ms))
        bt_row.commit()

        print(f"[LOG] Successfully wrote row for {date}")

    except Exception as e:
        print(f"[ERROR] Bigtable write failed: {e}")
        raise

# ---------- 3. Agent: Get Date ----------
def date_agent(state: AgentState) -> AgentState:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        **state,
        "date": today,
        "agent_status": "weather_agent"
    }

# ---------- 4. Agent: Get Weather ----------
def weather_agent(state: AgentState) -> AgentState:
    date = state["date"]
    weather = f"The weather on {date} is Sunny with clear skies."
    return {
        **state,
        "weather": weather,
        "agent_status": "confluence_agent"
    }

# ---------- 5. Agent: Update Confluence ----------
def confluence_agent(state: AgentState) -> AgentState:
    import os
    import requests

    date, weather = state["date"], state["weather"]

    # Confluence setup
    CONFLUENCE_BASE_URL = "https://baislaakshay13.atlassian.net/wiki"
    CONFLUENCE_USERNAME = "baisla.akshay13@gmail.com"#os.getenv("akshaya@hcltech.com")
    CONFLUENCE_API_TOKEN = ""#os.getenv("CONFLUENCE_API_TOKEN")
    SPACE_KEY = "VZagentica" 
    PAGE_TITLE = "Daily Weather Report"

    auth = (CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN)
    headers = {"Content-Type": "application/json"}

    # Step 1: Search for the page
    search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content"
    params = {
        "title": PAGE_TITLE,
        "spaceKey": SPACE_KEY,
        "expand": "version,body.storage"
    }
    resp = requests.get(search_url, auth=auth, headers=headers, params=params)
    data = resp.json()

    if resp.status_code != 200:
        raise Exception(f"[ERROR] Failed to search page: {resp.text}")

    if "results" in data and len(data["results"]) > 0:
        # Page exists → update it
        page = data["results"][0]
        page_id = page["id"]
        version = page["version"]["number"]
        old_body = page["body"]["storage"]["value"]

        new_content = f"{old_body}<p><b>{date}</b>: {weather}</p>"

        update_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
        payload = {
            "id": page_id,
            "type": "page",
            "title": PAGE_TITLE,
            "space": {"key": SPACE_KEY},
            "body": {
                "storage": {
                    "value": new_content,
                    "representation": "storage"
                }
            },
            "version": {"number": version + 1}
        }

        update_resp = requests.put(update_url, auth=auth, headers=headers, json=payload)
        if update_resp.status_code not in [200]:
            raise Exception(f"[ERROR] Failed to update page: {update_resp.text}")

        print(f"[LOG] Updated existing page '{PAGE_TITLE}'")

    else:
        # Page does not exist → create new page
        create_url = f"{CONFLUENCE_BASE_URL}/rest/api/content"
        new_body = f"<p><b>{date}</b>: {weather}</p>"
        payload = {
            "type": "page",
            "title": PAGE_TITLE,
            "space": {"key": SPACE_KEY},
            "body": {
                "storage": {
                    "value": new_body,
                    "representation": "storage"
                }
            }
        }

        create_resp = requests.post(create_url, auth=auth, headers=headers, json=payload)
        if create_resp.status_code not in [200, 201]:
            raise Exception(f"[ERROR] Failed to create page: {create_resp.text}")

        print(f"[LOG] Created new page '{PAGE_TITLE}'")

    return {**state, "agent_status": "done"}

# ---------- 6. Supervisor ----------
def supervisor(state: AgentState) -> str:
    return state["agent_status"] if state["agent_status"] in [
        "date_agent", "weather_agent", "confluence_agent"
    ] else END

# ---------- 7. Build Graph ----------
graph = StateGraph(AgentState)
graph.add_node("date_agent", date_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("confluence_agent", confluence_agent)
graph.add_conditional_edges("date_agent", supervisor)
graph.add_conditional_edges("weather_agent", supervisor)
graph.add_conditional_edges("confluence_agent", supervisor)
graph.set_entry_point("date_agent")
graph_executor = graph.compile()

# ---------- 8. Public Entry ----------
def run_agent_workflow() -> str:
    start_time = time.time()

    initial_state: AgentState = {
        "messages": [],
        "agent_status": "date_agent",
        "date": "",
        "weather": ""
    }

    final_state = graph_executor.invoke(initial_state)
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)

    save_to_bigtable(final_state["date"], final_state["weather"], duration_ms)
    return final_state["weather"]

# ---------- 9. Local Test ----------
if __name__ == "__main__":
    os.environ["CONFLUENCE_USERNAME"] = "your-email@example.com"
    os.environ["CONFLUENCE_API_TOKEN"] = "your-api-token"
    print(run_agent_workflow())

# rag-> confluence-> elastic search