from langgraph_supervisor import create_supervisor
from agents.weather_agent import create_weather_agent
from agents.country_agent import create_country_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

def create_supervisor_agent():
    weather = create_weather_agent()
    country = create_country_agent()

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0")

    supervisor_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are the supervisor of multiple AI assistants. Route user queries to the best agent."),
        MessagesPlaceholder(variable_name="messages")
    ])

    compiled = create_supervisor(
        model=llm,
        agents=[weather, country],
        supervisor_name="supervisor_agent",
        prompt=supervisor_prompt
    ).compile()

    print("✅ Compiled Supervisor Input Keys:", compiled.input_schema.schema().get("properties", {}).keys())
    return compiled