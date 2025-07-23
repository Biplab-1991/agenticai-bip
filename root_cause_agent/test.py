import os
import requests
import json
import time
import re
from typing import List, TypedDict, Optional

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.tools import tool

from pyvegas.langx.llm import VegasChatLLM, VegasChatVertexAI

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent # Still imported, but not used for the main agent in this version

# Initialize the LLM with VegasChatVertexAI (can be used for other agents or future expansions)
llm = VegasChatVertexAI(
    usecase_name="gts-h9vv-ccs-usecase",      # Your VEGAS Usecase Name
    context_name="gts-h9vv-ccs-context-withrag-uat",  # Your VEGAS Context ID
)

# Define the state for our LangGraph
class AgentState(TypedDict):
    """
    Represents the state passed between nodes in the LangGraph.
    - messages: A list of chat messages, primarily for final output.
    - source_space_key: Stores the source space key from the initial user request.
    - page_title_to_copy: Stores the title of the page to copy from the initial user request.
    - destination_space_key: Stores the destination space key from the initial user request.
    - source_page_content: Stores the content of the source page after retrieval. (Re-added)
    """
    messages: List[BaseMessage]
    source_space_key: str
    page_title_to_copy: str
    destination_space_key: str
    source_page_content: Optional[str] # Re-added this field to the TypedDict

# --- Confluence Helper Functions (not directly tools, but used by tools) ---

def _get_confluence_auth_details():
    """
    Helper to get Confluence authentication details.
    WARNING: Hardcoding credentials is highly insecure. For production,
    use environment variables or a secure secret management system.
    """
    CONFLUENCE_BASE_URL = "https://oneconfluence.verizon.com"
    CONFLUENCE_USERNAME = "" # Hardcoded as per user's provided code
    CONFLUENCE_PASSWORD = "" # Hardcoded as per user's provided code

    if not CONFLUENCE_USERNAME or not CONFLUENCE_PASSWORD:
        raise ValueError("CONFLUENCE_USERNAME and CONFLUENCE_PASSWORD must be set (preferably via environment variables).")
    
    return CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD

# --- Tools Definition ---

# NOTE: get_confluence_page_content and append_content_to_cloud_page are now
# called directly by Python nodes, not by an LLM agent. They are still defined
# as @tool for clarity and potential future LLM integration.

@tool
def get_confluence_page_content(space_key: str, page_title: str) -> str:
    """
    Retrieves the content of a specific Confluence page.
    This tool is used by the agent to read pages and understand their content.

    Args:
        space_key (str): The key of the Confluence space where the page resides.
        page_title (str): The exact title of the page to retrieve.
    Returns:
        str: The storage format content of the page, or an error message.
    """
    CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD = _get_confluence_auth_details()
    auth = (CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD)
    headers = {"Content-Type": "application/json"}

    print(f"[LOG] Attempting to retrieve content for page '{page_title}' in space '{space_key}'...")
    search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content"
    params = {
        "title": page_title,
        "spaceKey": space_key,
        "expand": "body.storage"
    }
    try:
        resp = requests.get(search_url, auth=auth, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "results" in data and len(data["results"]) > 0:
            page_content = data["results"][0]["body"]["storage"]["value"]
            print(f"[LOG] Successfully retrieved content for page '{page_title}'.")
            return page_content
        else:
            print(f"[LOG] Page '{page_title}' not found in space '{space_key}'.")
            return f"Error: Page '{page_title}' not found in space '{space_key}'."
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to retrieve content for page '{page_title}': {e}")
        return f"Error: Failed to retrieve content for page '{page_title}'. Details: {e}"

@tool
def append_content_to_cloud_page(destination_space_key: str, cloud_page_title: str, content_to_append: str) -> str:
    """
    Appends content to an existing cloud provider's page (AWS, Azure, GCP) in the destination space.
    If the cloud page does not exist, it creates it with the provided content.
    It checks if the exact content is already present before appending.

    Args:
        destination_space_key (str): The key of the destination Confluence space.
        cloud_page_title (str): The title of the cloud provider's page (e.g., "AWS", "Azure", "GCP").
        content_to_append (str): The content from the source page to append.
    Returns:
        str: A summary message of the operation.
    """
    CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD = _get_confluence_auth_details()
    auth = (CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD)
    headers = {"Content-Type": "application/json"}

    print(f"\n--- Starting Content Appending Operation ---")
    print(f"Destination Space: '{destination_space_key}', Target Cloud Page: '{cloud_page_title}'")

    # --- Step 1: Search for the target cloud page and get its current content ---
    search_url = f"{CONFLUENCE_BASE_URL}/rest/api/content"
    params = {
        "title": cloud_page_title,
        "spaceKey": destination_space_key,
        "expand": "version,body.storage" # Need version for update, and current content
    }
    
    page_id = None
    current_version = 0
    existing_content = ""

    try:
        print(f"[LOG] Searching for cloud page: '{cloud_page_title}' in space '{destination_space_key}'...")
        resp = requests.get(search_url, auth=auth, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "results" in data and len(data["results"]) > 0:
            page = data["results"][0]
            page_id = page["id"]
            current_version = page["version"]["number"]
            existing_content = page["body"]["storage"]["value"]
            print(f"[LOG] Cloud page '{cloud_page_title}' found. ID: {page_id}, Version: {current_version}.")
            print(f"[DEBUG] Existing content snippet: {existing_content[:100]}...")
        else:
            print(f"[LOG] Cloud page '{cloud_page_title}' not found. Will attempt to create it.")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to search for cloud page '{cloud_page_title}': {e}. Assuming page does not exist and attempting to create if content is new.")
        # If search fails, assume page doesn't exist and proceed to create if content is new.

    # --- Step 2: Check if content_to_append is already present ---
    # We'll normalize content_to_append to search for it without the added HTML blocks
    # This is a simple substring check. For more robust checks (e.g., ignoring whitespace, HTML tags),
    # you might need a more sophisticated diffing library or HTML parser.
    if content_to_append in existing_content:
        print(f"[INFO] The content to append is already present in page '{cloud_page_title}'. No changes will be made.")
        return f"Content from source page already exists in Confluence page '{cloud_page_title}'. No update performed."

    # --- Step 3: Append or Create Content ---
    # Ensure appended content is wrapped in a paragraph or similar block for structure
    new_content_block = f"<p>--- Content from Source Page: {time.strftime('%Y-%m-%d %H:%M:%S')} ---</p>{content_to_append}<p>--- End of Source Page Content ---</p>"
    new_page_content = f"{existing_content}{new_content_block}"

    if page_id: # Page exists, so update it
        update_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
        payload = {
            "id": page_id,
            "type": "page",
            "title": cloud_page_title,
            "space": {"key": destination_space_key},
            "body": {
                "storage": {
                    "value": new_page_content,
                    "representation": "storage"
                }
            },
            "version": {"number": current_version + 1}
        }
        try:
            print(f"[LOG] Sending PUT request to update page '{cloud_page_title}'...")
            update_resp = requests.put(update_url, auth=auth, headers=headers, json=payload)
            update_resp.raise_for_status()
            print(f"[SUCCESS] Successfully appended content to page '{cloud_page_title}'.")
            return f"Successfully appended content to Confluence page '{cloud_page_title}' in space '{destination_space_key}'."
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to update page '{cloud_page_title}': {e}")
            return f"Error: Failed to append content to page '{cloud_page_title}'. Details: {e}"
    else: # Page does not exist, so create it
        create_url = f"{CONFLUENCE_BASE_URL}/rest/api/content"
        payload = {
            "type": "page",
            "title": cloud_page_title,
            "space": {"key": destination_space_key},
            "body": {
                "storage": {
                    "value": new_page_content, # Initial content is the appended content
                    "representation": "storage"
                }
            }
        }
        try:
            print(f"[LOG] Sending POST request to create new page '{cloud_page_title}'...")
            create_resp = requests.post(create_url, auth=auth, headers=headers, json=payload)
            create_resp.raise_for_status()
            created_page_data = create_resp.json()
            print(f"[SUCCESS] Successfully created new page '{cloud_page_title}' with content. New ID: {created_page_data['id']}")
            return f"Successfully created Confluence page '{cloud_page_title}' in space '{destination_space_key}' and added content."
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to create page '{cloud_page_title}': {e}")
            return f"Error: Failed to create page '{cloud_page_title}'. Details: {e}"

# --- New Node: Retrieves source content ---
def retrieve_source_content_node(state: AgentState) -> dict:
    """
    Retrieves the content of the source page using the get_confluence_page_content tool.
    Returns the raw content string to be passed to the next node.
    """
    source_space_key = state["source_space_key"]
    page_title_to_copy = state["page_title_to_copy"]

    print(f"[LOG] Node: retrieve_source_content_node - Fetching content for '{page_title_to_copy}' from '{source_space_key}'.")
    
    # CORRECTED: Call the .invoke() method on the tool
    content = get_confluence_page_content.invoke({
        "space_key": source_space_key,
        "page_title": page_title_to_copy
    })
    
    # Return the content to be passed to the next node
    return {"source_page_content": content}

# --- New Node: Processes content and calls append tool ---
def process_and_append_content_node(state: AgentState) -> dict:
    """
    This node takes the source page content, identifies the cloud provider,
    and then calls the append_content_to_cloud_page tool.
    """
    source_content = state.get("source_page_content", "")
    destination_space_key = state.get("destination_space_key")
    page_title_to_copy = state.get("page_title_to_copy") # For logging purposes

    # Check if source_content is valid before proceeding
    if not source_content or "Error: Page" in source_content: # Check for tool error message
        print(f"[ERROR] Node: process_and_append_content_node - No valid source page content available. Aborting.")
        # Return an error message to be captured as the final output
        return {"messages": state["messages"] + [AIMessage(content=f"Error: Could not retrieve source page content. {source_content}")]}

    # --- Identify Cloud Provider (Programmatic for reliability) ---
    cloud_page_title = "AWS" # Default to AWS if not confidently identified
    content_lower = source_content.lower()

    if "azure" in content_lower or "microsoft azure" in content_lower:
        cloud_page_title = "Azure"
    elif "gcp" in content_lower or "google cloud" in content_lower:
        cloud_page_title = "GCP"
    elif "aws" in content_lower or "amazon web services" in content_lower:
        cloud_page_title = "AWS" # Explicitly set even if it's the default

    print(f"[LOG] Node: process_and_append_content_node - Identified cloud provider for '{page_title_to_copy}' as: '{cloud_page_title}'.")
    
    tool_output = append_content_to_cloud_page.invoke({
        "destination_space_key": destination_space_key,
        "cloud_page_title": cloud_page_title,
        "content_to_append": source_content
    })
    print(f"[LOG] Node: process_and_append_content_node - append_content_to_cloud_page returned: {tool_output}")

    # Return the tool's output as the final message
    return {"messages": state["messages"] + [AIMessage(content=tool_output)]}


# --- LangGraph Workflow ---
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("retrieve_content", retrieve_source_content_node)
workflow.add_node("process_and_append", process_and_append_content_node)

# Set the entry point
workflow.set_entry_point("retrieve_content")

# Define edges
workflow.add_edge("retrieve_content", "process_and_append")
workflow.add_edge("process_and_append", END)

# Compile the workflow
app = workflow.compile()

# --- Example Usage ---
async def main():
    # Print statement to confirm entry into main()
    print("[LOG] Entering main() function.")
    try:
        SOURCE_SPACE_KEY = "CLOUD"   
        PAGE_TITLE_TO_COPY = "AWS Services being Tagged" 
        DESTINATION_SPACE_KEY = "VZNOV" 

        print("\n" + "="*80)
        print(f"                 STARTING CLOUD CONTENT MIGRATION REQUEST                 ")
        print("="*80 + "\n")
        print(f"Request: Copy content of page '{PAGE_TITLE_TO_COPY}' from '{SOURCE_SPACE_KEY}' to append into its respective cloud page in '{DESTINATION_SPACE_KEY}'.")

        # The initial inputs to the graph
        inputs = {
            "messages": [HumanMessage(content=f"Please take the content of the page titled '{PAGE_TITLE_TO_COPY}' from space '{SOURCE_SPACE_KEY}' and append it to the relevant cloud provider's page in space '{DESTINATION_SPACE_KEY}'.")],
            "source_space_key": SOURCE_SPACE_KEY,
            "page_title_to_copy": PAGE_TITLE_TO_COPY,
            "destination_space_key": DESTINATION_SPACE_KEY
        }

        final_state = app.invoke(inputs)
        print("\n--- FINAL CLOUD CONTENT MIGRATION RESPONSE ---")
        # The final message should now be the output from the append_content_to_cloud_page tool
        if final_state["messages"]:
            print(final_state["messages"][-1].content)
        else:
            print("No final message from the workflow.")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] An unexpected error occurred during main execution: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
