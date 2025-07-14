from langgraph.graph import StateGraph, END
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

# State schema
class InputAgentState(dict):
    pass

# Gemini setup
gemini = ChatGoogleGenerativeAI(model="gemini-pro")
parser = StrOutputParser()

# LangChain Runnable to process user dialog
class InputAgent(Runnable):

    def invoke(self, state: InputAgentState) -> InputAgentState:
        dialog = state.get("dialog", [])
        last_input = state.get("last_input", "")
        dialog.append(last_input)

        prompt = f"""
You are a helpful assistant that collects user input and summarizes it into a single clear problem statement.

Dialog so far: {dialog}

Generate a JSON output:
{{
    "dialog": [...],
    "final problem statement": "...",
    "status": "complete" or "incomplete"
}}

Only return the JSON.
"""
        response = gemini.invoke([HumanMessage(content=prompt)])
        try:
            json_response = eval(response.content)  # safer alternatives: json.loads() with formatting enforcement
        except:
            json_response = {
                "dialog": dialog,
                "final problem statement": "",
                "status": "incomplete"
            }

        return {
            "dialog": json_response["dialog"],
            "final_problem_statement": json_response["final problem statement"],
            "status": json_response["status"]
        }

# Build LangGraph
def build_input_agent_graph():
    builder = StateGraph(InputAgentState)

    builder.add_node("collect_input", InputAgent())

    builder.set_entry_point("collect_input")
    builder.add_conditional_edges(
        "collect_input",
        lambda state: END if state["status"] == "complete" else "collect_input"
    )

    return builder.compile()
