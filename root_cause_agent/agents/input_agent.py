import json
from langgraph.graph import StateGraph, END
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import List, Literal, TypedDict

# -----------------------
# State Schema
# -----------------------

class InputAgentState(TypedDict):
    dialog: List[str]
    last_input: str
    status: Literal["complete", "incomplete"]
    final_problem_statement: str


# -----------------------
# Gemini Setup
# -----------------------
gemini = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Inject via env or secret
    )

# -----------------------
# Input Agent Definition
# -----------------------
class InputAgent(Runnable):
    def invoke(self, state: dict, config: dict = None) -> InputAgentState:
        #print("📥 State received by InputAgent:", state)  # 🔍 Debug

        dialog = state.get("dialog", [])
        last_input = state.get("last_input", "")
        #dialog.append(last_input)
        #print("🗣️ last_input in InputAgent:", last_input)

        prompt = f"""
You are a helpful assistant collecting information about a user's technical issue. The goal is to build a clear and complete problem statement by asking intelligent follow-up questions.

You must:
- Record the full dialog in a list
- Extract the current problem statement (if possible)
- Ask the user for more information if anything important is missing

Return only a JSON like:
{{
  "dialog": [... list of user messages ...],
  "final_problem_statement": "... summary of issue ...",
  "status": "complete" or "incomplete",
  "next_question": "If status is incomplete, ask this question next"
}}

DO NOT assume the cloud provider or access method unless stated.
If the user says "can't access VM", you should ask:
- What cloud provider are you using?
- Are you trying to SSH, access via browser, or something else?

Dialog so far:
{dialog}

New input from user:
{last_input}

Return only valid JSON. Do not wrap in Markdown or explanation.
"""




        try:
            response = gemini.invoke([HumanMessage(content=prompt)])
            #print("🔎 Gemini raw output:", response.content)

            json_content = response.content.strip()
            cleaned = json_content.strip().strip("```json").strip("```")
            parsed = json.loads(cleaned)

            # ✅ Append the user's input locally

            if parsed.get("status") == "incomplete":
                followup = parsed.get("next_question", "")
                last_input = input(f"🤖 {followup}\n👉 ")
                dialog.append({"role": "assistant", "content": followup})
                # dialog.append({"role": "user", "content": last_input})
            dialog.append({"role": "user", "content": last_input})

            if parsed.get("status") == "complete":
                return {
                    "dialog": dialog,
                    "final_problem_statement": parsed.get("final_problem_statement", ""),
                    "status": parsed.get("status", "incomplete"),
                    "next_question": parsed.get("next_question", ""),
                    "last_input": ""
                }

            #raise ValueError(f"❌ Unexpected Gemini response format:\n{json_content}")


        except Exception as e:
            print("⚠️ Gemini failed to parse JSON:", e)
            dialog.append(last_input)  # Still append even if error
            return {
                "dialog": dialog,
                "final_problem_statement": "",
                "status": "incomplete",
                "last_input": "",
                "next_question": ""
            }


# -----------------------
# Build LangGraph Agent
# -----------------------
def build_input_agent_graph():
    builder = StateGraph(InputAgentState)

    builder.add_node("collect_input", InputAgent())

    builder.set_entry_point("collect_input")
    builder.add_conditional_edges(
        "collect_input",
        lambda state: END if state.get("status") == "complete" else "collect_input"
    )

    return builder.compile()
