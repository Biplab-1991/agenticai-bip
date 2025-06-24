from mcp.server.fastmcp import FastMCP
# Initialize the FastMCP server with a name "Math"
mcp = FastMCP("Math")

@mcp.tool()
def web_search(query: str) -> str:
    """Searches the web for information related to the query."""
    print(f"\n--- Research Agent: Performing web search for: '{query}' ---")
    # Simulate a web search result based on common expected queries
    if "US GDP in 2024" in query:
        return "Based on various economic forecasts, the estimated nominal US GDP for 2024 is around $29.184 trillion."
    elif "New York state GDP in 2024" in query:
        return "Recent economic reports indicate New York state's GDP for 2024 is estimated to be around $2.297 trillion."
    elif "AI on education" in query:
        return "Key impacts of AI on education include personalized learning, automation of administrative tasks, and enhanced data analytics for student performance."
    elif "history of AI" in query:
        return "AI's history dates back to the 1950s with the Dartmouth workshop. Early AI focused on symbolic reasoning and expert systems."
    else:
        # Use a real search tool if configured, otherwise a generic message
        try:
            # If you configure a real search tool, uncomment the line below and ensure it's passed here.
            # return brave_search_tool.run(query)
            return f"Found some general information about: {query}" # Fallback
        except Exception as e:
            return f"Simulated search for '{query}': No specific data found, error: {e}"
        

if __name__ == "__main__":
    # This block runs the server when the script is executed directly.
    # It uses 'stdio' transport, which means it communicates over standard input/output.
    # For multiple servers, it's common to run them in separate processes or use HTTP transport.
    #print("Starting Math MCP server on port 8000 (default)...")
    mcp.run(transport="stdio")