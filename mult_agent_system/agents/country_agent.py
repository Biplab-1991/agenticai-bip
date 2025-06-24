from langgraph.prebuilt import create_react_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

@tool
def get_country_details(country: str) -> str:
    """Returns basic info about a country (dummy function)."""
    return f"{country} is a country with its own government and borders."

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0")

def create_country_agent():
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a country assistant. Use tools to answer questions."),
        ("human", "{input}")
    ])

    tools = [get_country_details]

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=prompt,
        name="country_agent"  # needed for langgraph-supervisor
    )
    return agent
