from mcp.server.fastmcp import FastMCP
# Initialize the FastMCP server with a name "Math"
mcp = FastMCP("Math")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    print(f"Math tool: Adding {a} + {b}")
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    print(f"Math tool: Multiplying {a} * {b}")
    return a * b

if __name__ == "__main__":
    # This block runs the server when the script is executed directly.
    # It uses 'stdio' transport, which means it communicates over standard input/output.
    # For multiple servers, it's common to run them in separate processes or use HTTP transport.
    print("Starting Math MCP server on port 8000 (default)...")
    mcp.run(transport="stdio")