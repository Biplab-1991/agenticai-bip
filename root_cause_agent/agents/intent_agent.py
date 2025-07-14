from agents.tools.dialogflow_tool import dialogflow_stub
from agents.tools.rag_tool import rag_stub
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage

class IntentAgentState(dict):
    pass

gemini = ChatGoogleGenerativeAI(model="gemini-pro")

class IntentAgent(Runnable):
    def invoke(self, state: IntentAgentState) -> IntentAgentState:
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
