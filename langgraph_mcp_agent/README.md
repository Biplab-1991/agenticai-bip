# 🤖 LangGraph MCP Agent Example

This project demonstrates how to connect a local [FastMCP](https://github.com/lowin/fastmcp) server with a [LangGraph](https://github.com/langchain-ai/langgraph) agent using the `MultiServerMCPClient` adapter. It uses an `add` tool exposed via HTTP, invoked through a LangGraph agent powered by an LLM (OpenAI by default).

---

## 📂 Project Structure

langgraph_mcp_agent/
├── mcp_server.py # FastMCP server with add/subtract tools
├── agent.py # LangGraph agent using MultiServerMCPClient
├── requirements.txt # Python dependencies


# Create and activate virtualenv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

in one terminal
python mcp_server.py

in another terminal
python agent.py

You should see the result of a tool invocation like:
42

use 
npx @modelcontextprotocol/inspector only to test mcp server

