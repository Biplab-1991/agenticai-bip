from langgraph.graph import StateGraph, END
from agents.llm_input import llm_input_agent
from agents.executor import request_executor_agent
from agents.response_parser import response_parser_agent
from agents.verify_completion_agent import verify_completion_agent

def log_state_transition(state):
    print("\n🔄 Transitioning with state:")
    for k, v in state.items():
        if k in {"user_input", "original_user_input", "status", "verification_reason", "final_output"}:
            print(f"  {k}: {v}")
    print("-----------------------------")

graph = StateGraph(dict)

# Define nodes
graph.add_node("llm_input", llm_input_agent)
graph.add_node("execute_request", request_executor_agent)
graph.add_node("parse_response", response_parser_agent)
graph.add_node("verify_completion", verify_completion_agent)

# Entry point
graph.set_entry_point("llm_input")

# Retry logic for llm_input
graph.add_conditional_edges(
    "llm_input",
    lambda s: "llm_input" if s.get("retry") else "execute_request",
    {
        "llm_input": "llm_input",
        "execute_request": "execute_request"
    }
)

# Flow through execution and parsing
graph.add_edge("execute_request", "parse_response")
graph.add_edge("parse_response", "verify_completion")

# Decide whether to end or jump based on next_action
graph.add_conditional_edges(
    "verify_completion",
    lambda s: (
        END if s.get("status") == "done"
        else s.get("next_action", "llm_input")  # Use next_action if available
    ),
    {
        END: END,
        "llm_input": "llm_input",
        "execute_request": "execute_request"
    }
)

# Compile the app
app = graph.compile()

if __name__ == "__main__":
    while True:
        user_input = input("👉 Ask anything related to cloud (or type 'exit'): ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("👋 Exiting.")
            break

        state = {
            "user_input": user_input,
            "original_user_input": user_input
        }

        # Run LangGraph app
        result = app.invoke(state)

        # Print state transition
        log_state_transition(result)

        # Show final output
        final_output = result.get("final_output") or result.get("plan") or result
        print("\n✅ Final Answer or Plan:", final_output)
        print(f"✅ Returning status: {result.get('status')}, retry: {result.get('retry')}, reason: {result.get('verification_reason')}")

        # Stop if task is done
        if result.get("status") == "done":
            print("✅ Task completed.\n")
            break

        print("🤖 Let's try again. Could you please rephrase or provide more detail?\n")
