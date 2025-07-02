from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent
from langgraph.graph import END
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator
from rag_tool import rag_search_tool
import os
import dotenv
dotenv.load_dotenv()


# Define graph state
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

# Gemini model
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-05-20",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=1
)

# RAG agent
rag_agent = create_react_agent(
    model=llm,
    tools=[rag_search_tool],
    prompt=ChatPromptTemplate.from_messages([
        ("system", "You are a helpful document assistant. Use the 'rag_search_tool' to find answers in the document index."),
        ("human", "{messages}")
    ]),
    name="rag_agent"
)

# Supervisor agent to delegate
supervisor = create_supervisor(
    agents=[rag_agent],
    model=llm,
    prompt=(
        "You are a smart router supervising a document retrieval agent. "
        "Use the 'rag_agent' to answer any user question that may be answered using documents in Elasticsearch. "
        "Always route user queries to the 'rag_agent'."
    ),
    output_mode="full_history"
)

app = supervisor.compile()

# Run as chat interface
if __name__ == "__main__":
    chat_history = []
    print("\n💬 Start chatting with your RAG agent (type 'exit' to quit):")

    while True:
        user_input = input("You: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        chat_history = [HumanMessage(content=user_input)]

        try:
            final_state = None
            for state in app.stream({"messages": chat_history}, config={"recursion_limit": 30}):
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
