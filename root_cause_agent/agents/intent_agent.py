from agents.tools.dialogflow_tool import dialogflow_stub
from agents.tools.rag_tool import rag_stub
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage

class IntentAgentState(dict):
    """State schema used by the Intent Agent graph."""
    # Input from InputAgent
    dialog: list
    final_problem_statement: str

    # Output from Dialogflow tool
    flow_type: str  # "guided" or "non-guided"

    # Output from RAG/Gemini
    documentation: list[str]

gemini = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Inject via env or secret
    )

class IntentAgent(Runnable):
    def invoke(self, state: dict, config: dict = None) -> IntentAgentState:
        dialog = state.get("dialog", [])
        final_problem_statement = state.get("final_problem_statement", "")

        # 1. Use Dialogflow Tool (stubbed)
        flow_type = dialogflow_stub(final_problem_statement)

        # 2. Use RAG Tool (stubbed)
        documentation = rag_stub(final_problem_statement)

        # 3. If RAG fails, use Gemini
        if not documentation:
            prompt = f"""
You are a cloud expert. Provide a list of troubleshooting steps for this problem:

Problem: {final_problem_statement}

Respond only with a numbered list of steps.
"""
            response = gemini.invoke([HumanMessage(content=prompt)])
            documentation = [step.strip() for step in response.content.strip().split("\n") if step.strip()]

        return {
            "dialog": dialog,
            "final_problem_statement": final_problem_statement,
            "flow_type": flow_type,
            "documentation": documentation
        }

def build_intent_agent_graph():
    builder = StateGraph(IntentAgentState)
    builder.add_node("intent_analysis", IntentAgent())
    builder.set_entry_point("intent_analysis")
    builder.set_finish_point("intent_analysis")
    return builder.compile()
