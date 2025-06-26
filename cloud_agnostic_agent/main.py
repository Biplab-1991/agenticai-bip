from langgraph.graph import StateGraph, END
from agents.llm_input import llm_input_agent
from agents.executor import request_executor_agent
from agents.response_parser import response_parser_agent

graph = StateGraph(dict)

# Add all nodes
graph.add_node("llm_input", llm_input_agent)
graph.add_node("execute_request", request_executor_agent)
graph.add_node("parse_response", response_parser_agent)

# Entry point
graph.set_entry_point("llm_input")

# Conditional edge based on retry flag
graph.add_conditional_edges(
    "llm_input",
    lambda s: "llm_input" if s.get("retry") else "execute_request",
    {
        "llm_input": "llm_input",
        "execute_request": "execute_request"
    }
)

# Continue the flow
graph.add_edge("execute_request", "parse_response")
graph.add_edge("parse_response", END)

# Compile the graph
app = graph.compile()

if __name__ == "__main__":
    user_input = input("Ask any cloud: ")
    result = app.invoke({"user_input": user_input,"original_user_input": user_input})

    final = result.get("final_output") or result.get("plan") or result
    print("\nFinal Answer:", final)
