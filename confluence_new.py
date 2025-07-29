import os
import re
import asyncio
from typing import List, TypedDict, Optional, Dict

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.tools import BaseTool # Import BaseTool type

from pyvegas.langx.llm import VegasChatLLM, VegasChatVertexAI

from langgraph.graph import StateGraph, END

# Import MultiServerMCPClient
from langchain_mcp_adapters.client import MultiServerMCPClient

# Initialize the LLM with VegasChatVertexAI (configured for Gemini)
llm = VegasChatVertexAI(
    usecase_name="gts-h9vv-ccs-usecase",
    context_name="gts-h9vv-ccs-context-withrag-uat"
)

# Define the state for our LangGraph
class AgentState(TypedDict):
    messages: List[BaseMessage]
    source_space_key: str
    page_title_to_copy: str
    destination_space_key: str
    source_page_content: Optional[str]
    summarized_content: Optional[str]
    identified_cloud_provider: Optional[str]
    status: str # "success" or "failure"
    # Change mcp_client to hold a dictionary of tools for direct invocation
    mcp_tools: Dict[str, BaseTool]

# --- Helper to get/initialize the MCP tools ---
async def _get_mcp_tools(state: AgentState) -> Dict[str, BaseTool]:
    """
    Retrieves the MCP tools from the state or initializes them if not present.
    This function now returns a dictionary of Tool objects, not the client itself.
    """
    # If tools are already in the state, return them
    if "mcp_tools" in state and state["mcp_tools"]:
        return state["mcp_tools"]
    else:
        # Initialize the MultiServerMCPClient
        client = MultiServerMCPClient({
            "confluence": { # The key "confluence" here is the server alias
                "url": "http://localhost:8080/mcp/",
                "transport": "streamable_http"
            }
        })
        # Get all tools from the client
        all_tools = await client.get_tools()
        
        # Create a dictionary of tools for easy access by their name.
        # The tool names returned by client.get_tools() will be the names
        # defined in your FastMCP server (e.g., "get_confluence_page_content"),
        # NOT "confluence.get_confluence_page_content" unless explicitly prefixed in FastMCP.
        tools_dict = {tool.name: tool for tool in all_tools}
        print(f"[LOG] Initialized MCP tools: {list(tools_dict.keys())}")
        return tools_dict

# --- Node: Retrieves source content ---
async def retrieve_source_content_node(state: AgentState) -> dict:
    source_space_key = state["source_space_key"]
    page_title_to_copy = state["page_title_to_copy"]

    print(f"[LOG] Node: retrieve_source_content_node - Fetching content for '{page_title_to_copy}' from '{source_space_key}' via MCP server.")
    
    # Get or initialize tools dictionary
    mcp_tools = await _get_mcp_tools(state) 
    
    # Get the specific tool by its full name.
    # IMPORTANT: Use the exact tool name as exposed by FastMCP, without the server alias prefix.
    get_confluence_page_content_tool = mcp_tools.get("get_confluence_page_content")

    if not get_confluence_page_content_tool:
        error_msg = "Error: 'get_confluence_page_content' tool not found in available MCP tools. Ensure its name matches the FastMCP definition."
        print(f"[ERROR] {error_msg}")
        return {
            "source_page_content": error_msg,
            "status": "failure",
            "messages": state["messages"] + [AIMessage(content=error_msg)],
            "mcp_tools": mcp_tools # Pass tools to next state
        }

    content = ""
    try:
        # Call the tool's ainvoke method with the required parameters
        result = await get_confluence_page_content_tool.ainvoke({
            "space_key": source_space_key,
            "page_title": page_title_to_copy
        })
        content = result # The result from ainvoke is the tool's output
    except Exception as e:
        content = f"Error calling get_confluence_page_content tool: {e}"
        print(f"[ERROR] {content}")

    # Check for errors in the content or if content is empty
    if "Error: Page" in content or not content or "Error calling" in content:
        return {
            "source_page_content": content,
            "status": "failure",
            "messages": state["messages"] + [AIMessage(content=f"Error: Could not retrieve source page content. {content}")],
            "mcp_tools": mcp_tools # Pass tools to next state
        }
    return {"source_page_content": content, "mcp_tools": mcp_tools} # Pass tools to next state

# --- Node: Summarizes content and identifies cloud provider using LLM ---
async def summarize_and_identify_cloud_node(state: AgentState) -> dict:
    source_content = state.get("source_page_content", "")
    page_title_to_copy = state.get("page_title_to_copy")
    mcp_tools = state["mcp_tools"] # Get tools from state

    if not source_content or "Error: Page" in source_content or "Error calling" in source_content:
        print(f"[ERROR] Node: summarize_and_identify_cloud_node - No valid source page content to process. Aborting.")
        return {
            "messages": state["messages"] + [AIMessage(content=f"Error: Could not retrieve source page content for summarization/identification. {source_content}")],
            "status": "failure",
            "mcp_tools": mcp_tools # Pass tools to next state
        }

    print(f"[LOG] Node: summarize_and_identify_cloud_node - Summarizing and identifying cloud provider for '{page_title_to_copy}'.")

    prompt = (
        f"Please perform two tasks for the following Confluence page content titled '{page_title_to_copy}':\n\n"
        f"1. **Summarize the content:** Focus on the main points and key information, making it concise and easy to understand. Retain all critical details, especially regarding cloud services, configurations, or relevant technical specifications.\n\n"
        f"2. **Identify the primary cloud provider:** Determine if the content primarily discusses AWS, Azure, or GCP. If no specific cloud provider is clearly indicated, default to 'AWS'. Your answer for this part should be *only* 'AWS', 'Azure', or 'GCP'.\n\n"
        f"Please format your response as follows:\n\n"
        f"SUMMARY:\n"
        f"{{Your concise summary here}}\n\n"
        f"CLOUD_PROVIDER:\n"
        f"{{AWS, Azure, or GCP}}"
        f"\n\nHere is the content:\n\n{source_content}"
    )

    try:
        llm_response_message = await llm.ainvoke(prompt)
        llm_response_content = llm_response_message.content

        summarized_text = "No summary found."
        identified_cloud = "AWS" 

        summary_match = re.search(r"SUMMARY:\n(.*?)(?=\n\nCLOUD_PROVIDER:|$)", llm_response_content, re.DOTALL)
        if summary_match:
            summarized_text = summary_match.group(1).strip()

        cloud_match = re.search(r"CLOUD_PROVIDER:\n(AWS|Azure|GCP)", llm_response_content)
        if cloud_match:
            identified_cloud = cloud_match.group(1).strip()
        else:
            print(f"[WARNING] LLM did not clearly identify cloud provider. Defaulting to '{identified_cloud}'. Response: {llm_response_content[:200]}...")


        print(f"[LOG] Node: summarize_and_identify_cloud_node - Content summarized and cloud provider identified ('{identified_cloud}').")
        return {
            "summarized_content": summarized_text,
            "identified_cloud_provider": identified_cloud,
            "mcp_tools": mcp_tools # Pass tools to next state
        }
    except Exception as e:
        print(f"[ERROR] Node: summarize_and_identify_cloud_node - Failed to process content with LLM: {e}")
        return {
            "messages": state["messages"] + [AIMessage(content=f"Error: Failed to summarize content or identify cloud provider from page '{page_title_to_copy}'. Details: {e}")],
            "status": "failure",
            "mcp_tools": mcp_tools # Pass tools to next state
        }

# --- Node: Processes content and calls append tool ---
async def process_and_append_content_node(state: AgentState) -> dict:
    content_to_append = state.get("summarized_content", "")
    destination_space_key = state.get("destination_space_key")
    page_title_to_copy = state.get("page_title_to_copy")
    cloud_page_title = state.get("identified_cloud_provider")
    mcp_tools = state["mcp_tools"] # Get tools from state

    if not content_to_append:
        print(f"[ERROR] Node: process_and_append_content_node - No summarized content available to append. Aborting.")
        return {
            "messages": state["messages"] + [AIMessage(content=f"Error: No summarized content available to append.")],
            "status": "failure",
            "mcp_tools": mcp_tools # Pass tools to next state
        }

    if not cloud_page_title:
        print(f"[ERROR] Node: process_and_append_content_node - No cloud provider identified by LLM. Aborting.")
        return {
            "messages": state["messages"] + [AIMessage(content=f"Error: No cloud provider could be identified for page '{page_title_to_copy}'.")],
            "status": "failure",
            "mcp_tools": mcp_tools # Pass tools to next state
        }

    print(f"[LOG] Node: process_and_append_content_node - Using cloud provider identified by LLM: '{cloud_page_title}'.")
    
    # Get the specific tool by its full name.
    # IMPORTANT: Use the exact tool name as exposed by FastMCP, without the server alias prefix.
    append_content_tool = mcp_tools.get("append_content_to_cloud_page")

    if not append_content_tool:
        error_msg = "Error: 'append_content_to_cloud_page' tool not found in available MCP tools. Ensure its name matches the FastMCP definition."
        print(f"[ERROR] {error_msg}")
        return {
            "messages": state["messages"] + [AIMessage(content=error_msg)],
            "status": "failure",
            "mcp_tools": mcp_tools # Pass tools to next state
        }

    tool_output = ""
    try:
        # Call the tool's ainvoke method with the required parameters
        result = await append_content_tool.ainvoke({
            "destination_space_key": destination_space_key,
            "cloud_page_title": cloud_page_title,
            "content_to_append": content_to_append
        })
        tool_output = result
    except Exception as e:
        tool_output = f"Error calling append_content_to_cloud_page tool: {e}"
        print(f"[ERROR] {tool_output}")

    print(f"[LOG] Node: process_and_append_content_node - append_content_to_cloud_page returned: {tool_output}")

    if "Error:" in tool_output:
        final_status = "failure"
    else:
        final_status = "success"

    return {
        "messages": state["messages"] + [AIMessage(content=tool_output)],
        "status": final_status,
        "mcp_tools": mcp_tools # It's good practice to keep passing it even at END for consistency
    }

# --- LangGraph Workflow ---
workflow = StateGraph(AgentState)

workflow.add_node("retrieve_content", retrieve_source_content_node)
workflow.add_node("summarize_and_identify", summarize_and_identify_cloud_node)
# Corrected the typo in the node name here
workflow.add_node("process_and_append", process_and_append_content_node)

workflow.set_entry_point("retrieve_content")

workflow.add_edge("retrieve_content", "summarize_and_identify")
workflow.add_edge("summarize_and_identify", "process_and_append")
workflow.add_edge("process_and_append", END)

confluence_agent_app = workflow.compile()
