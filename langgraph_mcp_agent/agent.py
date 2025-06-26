import asyncio
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_google_genai import ChatGoogleGenerativeAI

async def main():
    # Connect to your MCP server
    client = MultiServerMCPClient({
        "math": {
            "url": "https://mcp-server-173768923341.us-central1.run.app/mcp/",
            "transport": "streamable_http"
        }
    })

    # Load tools
    tools = await client.get_tools()

    print("Requesting tools from MCP server...")
    try:
        tools = await client.get_tools()
        print("Tools received:")
        for tool in tools:
            print(" -", tool.name)
        # LLM (replace with your key/model as needed)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyBo4a3W2yzFg_YMdIBSYgKIBn6JDnf2Gc4")

        # Create LangGraph tool-using agent
        agent = create_react_agent(llm, tools)

        # Ask something that uses a tool
        result = await agent.ainvoke({
            "messages": [HumanMessage(content="What's 25 - 17?")]
        })

        print(result["messages"][-1].content)
    except Exception as e:
        print("❌ Failed to get tools from MCP server:")
        print(e)

    

if __name__ == "__main__":
    asyncio.run(main())
