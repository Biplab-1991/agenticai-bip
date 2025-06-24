from langgraph.prebuilt import create_react_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

@tool
def get_weather(city: str) -> str:
    """Returns weather for a city (dummy function)."""
    return f"The weather in {city} is 30°C and sunny."

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0")


def create_weather_agent():
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a weather assistant. Use tools to answer questions."),
        ("human", "{input}")
    ])

    tools = [get_weather]  # assume get_weather is a langchain-compatible tool

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=prompt,
        name="weather_agent"  # if using langgraph-supervisor
    )
    return agent
