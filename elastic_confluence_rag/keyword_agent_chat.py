from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent
from langgraph.graph import END
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from typing import Annotated, TypedDict
import operator
import os
from dotenv import load_dotenv
from keyword_search_tool import keyword_search_tool

load_dotenv()

# Define agent state
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

# Initialize Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-05-20",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.5
)

# Create agent using keyword search tool
keyword_agent = create_react_agent(
    model=llm,
    tools=[keyword_search_tool],
    prompt=ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant. Use the 'keyword_search_tool' to search documents by keyword."),
        ("human", "{messages}")
    ]),
    name="keyword_agent"
)

# Create supervisor to route all prompts to this agent
supervisor = create_supervisor(
    agents=[keyword_agent],
    model=llm,
    prompt=(
        "You are a supervisor for a document search assistant. "
        "Always route queries to the 'keyword_agent' to search content using keyword matching."
    ),
    output_mode="full_history"
)

# Compile into runnable graph
app = supervisor.compile()

# Run as CLI chatbot
if __name__ == "__main__":
    chat_history = []
    print("\n💬 Keyword Search Agent Ready! Type your question (or 'exit' to quit):")

    while True:
        user_input = input("You: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        chat_history = [HumanMessage(content=user_input)]

        try:
            final_state = None
            for state in app.stream({"messages": chat_history}, config={"recursion_limit": 300}):
                final_state = state

            if final_state and "supervisor" in final_state:
                messages = final_state["supervisor"].get("messages", [])
                last_msg = next(
                    (m.content for m in reversed(messages)
                     if isinstance(m, AIMessage)
                     and m.content.strip()
                     and not m.additional_kwargs.get("function_call")),
                    None
                )
                print(f"Assistant: {last_msg}")
            else:
                print("Assistant: [Unexpected output]")
        except Exception as e:
            print(f"Assistant: [ERROR] {e}")
