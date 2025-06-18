import os
from typing import Annotated, List, Tuple, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.graph import StateGraph, END
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio


llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyBo4a3W2yzFg_YMdIBSYgKIBn6JDnf2Gc4")
        

@tool
def draft_section(topic: str, research_notes: str) -> str:
    """Drafts a section of the report based on the topic and research notes."""
    print(f"\n--- Writing Agent: Drafting section for: '{topic}' ---")
    return f"Draft for '{topic}': {research_notes}\n\n[Further details would be added here.]"

@tool
def critique_draft(draft: str) -> str:
    """Critiques a draft section and provides suggestions for improvement."""
    print(f"\n--- Editing Agent: Critiquing draft ---")
    if "personalized learning" in draft:
        return "Critique: The section on personalized learning is good, but could benefit from examples of specific AI tools. Suggest adding a paragraph on adaptive learning platforms."
    return "Critique: Draft looks good. No major issues found."

async def _get_mcp_tools():
    """Helper async function to get tools."""
    mcp_client = MultiServerMCPClient(
        connections={
            "math": {
                "command": "python",
                "args": ["search_server.py"],
                "transport": "stdio",
                "port": 8000,
            }
        }
    )
    # It's important to start the client's servers before getting tools
    #await mcp_client.start_servers() # Ensure servers are started
    tools = await mcp_client.get_tools()
    # You might want to stop servers if this is a one-off and you don't need them running
    # If the client is going to be used by the agent, keep them running.
    # await mcp_client.stop_servers()
    return tools, mcp_client # Return the client as well if you need to use it later

# Get tools at the global scope for immediate use
# This will block until the tools are retrieved
global_tools, global_mcp_client = asyncio.run(_get_mcp_tools())

research_agent = create_react_agent(
    model=llm,
    tools=global_tools,
    prompt=(
        "You are a research agent.\n\n"
        "INSTRUCTIONS:\n"
        "- Assist ONLY with research-related tasks, DO NOT do any math\n"
        "- After you're done with your tasks, respond to the supervisor directly\n"
        "- Respond ONLY with the results of your work, do NOT include ANY other text."
    ),
    name="research_agent",
)


writing_agent = create_react_agent(
    model=llm,
    tools=[draft_section],
    prompt=(
        "You are a writing agent.\n\n"
        "INSTRUCTIONS:\n"
        "- Assist ONLY with writing-related tasks\n"
        "- After you're done with your tasks, respond to the supervisor directly\n"
        "- Respond ONLY with the results of your work, do NOT include ANY other text."
    ),
    name="writing_agent",
)

editing_agent = create_react_agent(
    model=llm,
    tools=[critique_draft],
    prompt=(
        "You are a editing agent.\n\n"
        "INSTRUCTIONS:\n"
        "- Assist ONLY with edit-related tasks\n"
        "- After you're done with your tasks, respond to the supervisor directly\n"
        "- Respond ONLY with the results of your work, do NOT include ANY other text."
    ),
    name="editing_agent", 
)

# Research Team Supervisor
research_supervisor_graph = create_supervisor(
    agents=[
        research_agent
    ],
    model=llm,
    prompt=(
        "You are the research supervisor. "
        "Your goal is to gather all necessary information by delegating tasks "
        "to the 'research_expert' (for web searches) "
        "When you have gathered sufficient information to answer the user's request, "
        "or if the user explicitly asks you to, you should call 'FINISH'."
        "You should respond with detailed findings relevant to the query."
    ),
    supervisor_name="research_team_supervisor",
).compile(name="research_team") # Compile creates a runnable graph for this supervisor

# Writing Team Supervisor
writing_team_supervisor_graph = create_supervisor(
    agents=[
        writing_agent, # Pass the node function
        editing_agent # Pass the node function
    ],
    model=llm,
    prompt=(
        "You are the writing team supervisor. "
        "Your goal is to draft and refine sections of a report. "
        "Use the 'writing_expert' to draft content and the 'editing_expert' to critique it. "
        "When the report section is well-drafted and reviewed, you should call 'FINISH'."
        "You should respond with the final, polished draft of the section."
    ),
    supervisor_name="writing_team_supervisor",
).compile(name="writing_team") # Compile creates a runnable graph for this supervisor


# --- 7. Define Top-Level Supervisor ---
# This supervisor will orchestrate the mid-level supervisors.

# Treat the compiled mid-level supervisor graphs as "agents" for the top-level supervisor.
# We need to wrap them in a dictionary expected by create_supervisor.
# The 'name' here is what the supervisor LLM will use in its tool calls.
top_level_agents = [
    research_supervisor_graph,
    writing_team_supervisor_graph
]

top_level_supervisor = create_supervisor(
    agents=top_level_agents,
    model=llm,
    prompt=(
        "You are the main Report Generation Supervisor. "
        "Your primary role is to orchestrate the 'research_team' and the 'writing_team' "
        "to produce comprehensive reports based on user requests. "
        "\n\n"
        "**However, you are also capable of handling direct, specific queries that can be answered by the 'research_team' (which includes capabilities for math and weather information).** "
        "**If the user's request is a direct question (e.g., a math calculation, current weather, or a quick fact lookup), you should delegate it to the 'research_team'. Once the 'research_team' provides the answer, you should immediately call 'FINISH' with that answer.**"
        "\n\n"
        "For complex requests that require a detailed report: "
        "1. First, use the 'research_team' to gather all necessary information and conduct thorough research."
        "2. Once research is complete and sufficient, use the 'writing_team' to draft and refine the report sections."
        "3. When the entire report is generated and satisfactory, you should call 'FINISH'."
        "\n\n"
        "Your final response should be the complete report for complex requests, or the direct answer for simple queries."
    ),
    supervisor_name="top_level_supervisor",
)

# --- 8. Compile the Top-Level Graph ---
# This creates the final runnable application.
app = top_level_supervisor.compile()

# --- 9. Run the Multi-Supervisor System ---

async def main():
    #await global_mcp_client.start_servers()
    # Example 1: Basic report generation
    print("\n" + "="*80)
    print("                 STARTING REPORT GENERATION: AI on Education                 ")
    print("="*80 + "\n")
    inputs = {"messages": [HumanMessage(content="Generate a short report on the impact of AI on education, specifically focusing on personalized learning and administrative automation.")]}

    for i, s in enumerate(app.stream(inputs)):
        print(f"\n--- Step {i+1} ---")
        if "__end__" not in s:
            for key, value in s.items():
                print(f"  Node: {key}")
                if isinstance(value, dict) and "messages" in value:
                    for msg in value["messages"]:
                        print(f"    Message Type: {type(msg).__name__}")
                        print(f"    Content: {msg.content}")
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            print(f"    Tool Calls: {msg.tool_calls}")
                        if hasattr(msg, 'name') and msg.name:
                            print(f"    Sender/Name: {msg.name}")
                else:
                    print(f"    Raw Output: {value}")
        else:
            print(f"\n" + "="*80)
            print("                       REPORT GENERATION FINISHED                       ")
            print("="*80 + "\n")
            final_messages = s["__end__"]["messages"]
            for msg in final_messages:
                if isinstance(msg, HumanMessage) or isinstance(msg, ToolMessage):
                    print(f"Final Report Content:\n\n{msg.content}")

    print("\n\n" + "="*80)
    print("                 STARTING ANOTHER REQUEST: History of AI                 ")
    print("="*80 + "\n")
    inputs_2 = {"messages": [HumanMessage(content="Research the early history of AI and draft a short summary.")]}

    for i, s in enumerate(app.stream(inputs_2)):
        print(f"\n--- Step {i+1} ---")
        if "__end__" not in s:
            for key, value in s.items():
                print(f"  Node: {key}")
                if isinstance(value, dict) and "messages" in value:
                    for msg in value["messages"]:
                        print(f"    Message Type: {type(msg).__name__}")
                        print(f"    Content: {msg.content}")
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            print(f"    Tool Calls: {msg.tool_calls}")
                        if hasattr(msg, 'name') and msg.name:
                            print(f"    Sender/Name: {msg.name}")
                else:
                    print(f"    Raw Output: {value}")
        else:
            print(f"\n" + "="*80)
            print("                       REPORT GENERATION FINISHED                       ")
            print("="*80 + "\n")
            final_messages = s["__end__"]["messages"]
            for msg in final_messages:
                if isinstance(msg, HumanMessage) or isinstance(msg, ToolMessage):
                    print(f"Final Report Content:\n\n{msg.content}")

if __name__ == "__main__":
    asyncio.run(main())