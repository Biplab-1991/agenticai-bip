from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent
import requests
import json
from requests.structures import CaseInsensitiveDict
from langchain_google_genai import ChatGoogleGenerativeAÌ


# 1. Define the Graph State (same as before)
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

RAPIDAPI_KEY="d857e72ab9msh5fadf58e3968d4ep148671jsn1bc8eea221c9"
OPENWEATHERMAP_API_KEY="c6e6e4f39319819c7983ae9e3e626314"

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyBo4a3W2yzFg_YMdIBSYgKIBn6JDnf2Gc4")


# writing code for weather tool which uses a weather API
@tool
def get_current_weather(city: str, units: str = "metric") -> str:
    """
    Fetches the current weather conditions for a specified city using OpenWeatherMap.
    Returns temperature, main weather condition, and description.

    Args:
        city (str): The name of the city (e.g., "London", "New York", "Chennai").
        units (str): The unit system for temperature. 'metric' for Celsius (default),
                     'imperial' for Fahrenheit, or 'standard' for Kelvin.
    """
    base_url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "units": units,
        "appid": OPENWEATHERMAP_API_KEY
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        if data.get("cod") == 200:
            main_data = data.get("main", {})
            weather_data = data.get("weather", [{}])[0]
            temp = main_data.get("temp")
            feels_like = main_data.get("feels_like")
            humidity = main_data.get("humidity")
            description = weather_data.get("description")
            main_condition = weather_data.get("main")
            city_name_from_api = data.get("name") # Use city name from API response for accuracy

            unit_symbol = "°C" if units == "metric" else ("°F" if units == "imperial" else "K")

            return (
                f"Current weather in {city_name_from_api}: "
                f"{temp}{unit_symbol} (feels like {feels_like}{unit_symbol}), "
                f"Conditions: {main_condition} - {description}, "
                f"Humidity: {humidity}%."
            )
        else:
            return f"Error from OpenWeatherMap API for {city}: {data.get('message', 'Unknown error')} (Code: {data.get('cod')})"
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 404:
            return f"City '{city}' not found by OpenWeatherMap. Please check the spelling."
        elif status_code == 401:
            return "OpenWeatherMap API Key is invalid or expired. Please check your key."
        else:
            return f"HTTP error from OpenWeatherMap API for {city}: {e}"
    except requests.exceptions.ConnectionError as e:
        return f"Connection error to OpenWeatherMap API: {e}. Please check your internet connection."
    except requests.exceptions.Timeout as e:
        return f"Timeout error with OpenWeatherMap API: {e}."
    except json.JSONDecodeError:
        return f"Failed to decode JSON from OpenWeatherMap API response for {city}."
    except Exception as e:
        return f"An unexpected error occurred with OpenWeatherMap API for {city}: {e}"

@tool
def get_country_detail(country_name: str) -> str:
    """
    Fetches details about a country using the RapidAPI GeoDB API."""
    headers = CaseInsensitiveDict()
    headers["x-rapidapi-host"] = "wft-geo-db.p.rapidapi.com"
    # Use the RAPIDAPI_KEY from the environment variable directly
    headers["x-rapidapi-key"] = RAPIDAPI_KEY

    country_code = {
        "India": "IN",
        "United States": "US"
    }
    
    if country_name not in country_code:
        return f"Country code not available for {country_name}. Currently supports: {', '.join(country_code.keys())}"

    cntry_name_shrt_code = country_code[country_name]
    url = f"https://wft-geo-db.p.rapidapi.com/v1/geo/countries/{cntry_name_shrt_code}"
    
    print(f"Calling RapidAPI URL: {url}")
    
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        
        data = res.json()["data"]
        callingcode = data["callingCode"]
        currency = data["currencyCodes"][0]
        numberofregion = data["numRegions"]
        flaguri = data["flagImageUri"]
        
        return f"The currency in {country_name} is {currency} with calling code {callingcode}, number of region {numberofregion} and flag image {flaguri}"
    
    except requests.exceptions.RequestException as e:
        print(f"Error making RapidAPI request for {country_name}: {e}")
        return f"Couldn't retrieve details for {country_name} due to an API request error."
    except KeyError as e:
        print(f"Missing expected data in RapidAPI response for {country_name}: {e}")
        return f"Couldn't parse details for {country_name} from API response."
    except Exception as e:
        print(f"An unexpected error occurred in get_country_detail for {country_name}: {e}")
        return f"An unexpected error occurred while retrieving details for {country_name}."



# 2. Create Worker Agents (using create_react_agent for simplicity)
# These agents will use the tools we defined
weather_agent_node = create_react_agent(
    model=llm,
    tools=[get_current_weather],
    prompt=ChatPromptTemplate.from_messages([
        ("system", "You are a weather agent. Use the 'get_current_weather' tool to find weather information."),
        ("human", "{messages}"),
    ]),
    name="weather_agent", # Important for supervisor to identify
)

country_agent_node = create_react_agent(
    model=llm,
    tools=[get_country_detail],
    prompt=ChatPromptTemplate.from_messages([
        ("system", "You are a country information agent. Use the 'get_country_detail' tool to find country information."),
        ("human", "{messages}"),
    ]),
    name="country_agent", # Important for supervisor to identify
)

# 3. Create the Supervisor Workflow using create_supervisor
supervisior_agent = create_supervisor(
    agents=[weather_agent_node, country_agent_node],
    model=llm,
    prompt=(
        "You are a smart team supervisor managing a weather agent and a country information agent. "
        "Your goal is to direct user queries to the most appropriate agent or to finish the task."
        "When the user asks for weather information, use the 'weather_agent'."
        "When the user asks for country information, use the 'country_agent'."
        "If you have completed the user's request or if the request is not suitable for any agent, "
        "you can signal 'FINISH'."
    ),
    # Optional: Customize output mode if needed. Default is 'last_message'.
    # output_mode="full_history",
)

# Compile the graph
app = supervisior_agent.compile()


# 4. Invoke the Graph

print("--- Invoking with 'search' request ---")
input_state_1 = {"messages": [HumanMessage(content="What is the capital of India?")]}
for s in app.stream(input_state_1):
    print(s)
print("\n")

print("--- Invoking with 'creative' request ---")
input_state_2 = {"messages": [HumanMessage(content="Write a poem about a flying cat.")]}
for s in app.stream(input_state_2):
    print(s)
print("\n")

print("--- Invoking with a request that leads to FINISH ---")
input_state_3 = {"messages": [HumanMessage(content="Hello there!")]}
for s in app.stream(input_state_3):
    print(s)
print("\n")

print("--- Invoking with a mixed request (often defaults to research or needs more complex routing) ---")
input_state_4 = {"messages": [HumanMessage(content="Tell me a fact about space, then write a poem about it.")]}
for s in app.stream(input_state_4):
    print(s)
print("\n")


# Agents
# integrate agents into the supervisor
# test the agent first with queries to understand respective tool calling
# User query should be taken on runtime
# cmd conversation
# contextualize the agent