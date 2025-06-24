import os
import asyncio
from typing import List, TypedDict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage # Ensure ToolMessage is imported
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END

# Import the specific LLM you want to use.
from langchain_google_genai import ChatGoogleGenerativeAI

# IMPORTANT: Set your LLM API Key
os.environ["GOOGLE_API_KEY"] = "YOUR_GOOGLE_API_KEY" # REPLACE THIS WITH YOUR ACTUAL API KEY

# Instantiate the LLM explicitly
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyBo4a3W2yzFg_YMdIBSYgKIBn6JDnf2Gc4")

# 3. Define the LangGraph State and Graph
class AgentState(TypedDict):
    """Represents the state of the agent in the graph."""
    messages: List[BaseMessage]

# 4. Modified run_agent function to print messages with source tags
async def run_agent(query: str, app_instance):
    """
    Runs the LangGraph agent with a given user query and prints messages
    labeled by their source (Model or Tool).
    """
    inputs = {"messages": [HumanMessage(content=query)]}
    #print(f"\n--- User query: {query} ---")

    final_ai_message_content = None

    # Iterate through the streamed state changes
    async for s in app_instance.astream(inputs):
        if "agent" in s and s["agent"]["messages"]:
            # LangGraph can sometimes give partial messages or multiple messages in one step.
            # We process all messages in this state update to see the full flow.
            for message in s["agent"]["messages"]:
                if isinstance(message, AIMessage):
                    if message.tool_calls:
                        # This AIMessage is the model deciding to call a tool
                        print(f"Coming from Model (Tool Call Decision): {message.tool_calls}")
                        # If the model also had a "thought" before the tool call:
                        if message.content:
                            print(f"  Model Thought: {message.content}")
                    else:
                        # This AIMessage is the model providing a natural language response
                        print(f"Coming from Model (Content): {message.content}")
                        final_ai_message_content = f"Coming from Model (Content): {message.content}" # Capture the final content

                elif isinstance(message, ToolMessage):
                    # This is the output received from an executed tool
                    print(f"Coming from Tool (Output of '{message.name}'): {message.content}")
                    # You can also access message.tool_call_id here if needed

    print("--- Agent finished ---")
    if final_ai_message_content:
        print(f"Final AI Response: {final_ai_message_content}")
    else:
        print("Final AI Response: Agent completed without a clear final AI message content.")
    return final_ai_message_content

# Example usage (main function to orchestrate everything)
async def main():
    """
    Main function to demonstrate running the agent with various queries.
    """
    print("--- Starting LangGraph MCP Client Agent Demonstration ---")

    mcp_client = MultiServerMCPClient(
        connections={
            "math": {
                "command": "python",
                "args": ["math_server.py"],
                "transport": "stdio",
                "port": 8000,
            },
            "weather": {
                "command": "python",
                "args": ["weather_server.py"],
                "transport": "stdio",
                "port": 8001,
            }
        }
    )

    tools = await mcp_client.get_tools()
    #print(f"Discovered tools: {[tool.name for tool in tools]}")

    agent_executor = create_react_agent(llm, tools, debug=True)

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("agent", agent_executor)
    graph_builder.set_entry_point("agent")
    graph_builder.add_conditional_edges(
        "agent",
        lambda x: END if isinstance(x["messages"][-1], AIMessage) else "agent",
    )
    app = graph_builder.compile()

    # Test queries that should trigger tool usage
    await run_agent("what is 2 plus 2?", app)
    await run_agent("Calculate 12 multiplied by 5.", app)
    await run_agent("What's the weather in London?", app)
    await run_agent("Tell me a joke.", app)

    print("\n--- Demonstration Complete ---")

if __name__ == "__main__":
    asyncio.run(main())