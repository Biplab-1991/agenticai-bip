import asyncio
import logging
import os
from fastmcp import FastMCP

# Setup logger
logger = logging.getLogger(__name__)
logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)

# Initialize FastMCP with path="/" to expose /invoke directly
mcp = FastMCP("MCP Server on Cloud Run")

# Define tools
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    logger.info(f">>> Tool: 'add' called with {a} + {b}")
    return a + b

@mcp.tool()
def subtract(a: int, b: int) -> int:
    """Subtract two numbers."""
    logger.info(f">>> Tool: 'subtract' called with {a} - {b}")
    return a - b

# Start server
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 MCP server starting on http://0.0.0.0:{port}/invoke")

    asyncio.run(
        mcp.run_async(
            transport="streamable-http",
            host="0.0.0.0",
            port=port,
        )
    )
