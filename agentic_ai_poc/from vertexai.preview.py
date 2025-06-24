from vertexai.preview.generative_models import GenerativeModel, Tool, FunctionDeclaration
import vertexai
import requests
from requests.structures import CaseInsensitiveDict

# Initialize Vertex AI SDK
vertexai.init(project="dauntless-theme-461816-f6", location="us-central1")

# Function 1: Get city weather
get_city_weather_fn = FunctionDeclaration(
    name="get_city_weather",
    description="Fetches current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city_name": {"type": "string", "description": "Name of the city"}
        },
        "required": ["city_name"]
    }
)

# Function 2: Get city population (dummy example)
get_city_population_fn = FunctionDeclaration(
    name="get_city_population",
    description="Fetches the population for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city_name": {"type": "string", "description": "Name of the city"}
        },
        "required": ["city_name"]
    }
)

# Function 3: Get country details
get_country_detail_fn = FunctionDeclaration(
    name="get_country_detail",
    description="Fetches details of a country.",
    parameters={
        "type": "object",
        "properties": {
            "country_name": {"type": "string", "description": "Name of the country"}
        },
        "required": ["country_name"]
    }
)

tool = Tool(function_declarations=[get_city_weather_fn, get_city_population_fn, get_country_detail_fn])
model = GenerativeModel("gemini-2.5-flash-preview-05-20", tools=[tool])

# 1. Define your functions

def get_city_weather(city_name: str) -> str:
    return f"Weather info for {city_name} here (mocked)."

def get_city_population(city_name: str) -> str:
    populations = {"New York": "8.4 million", "London": "9 million", "Paris": "2.1 million"}
    return f"The population of {city_name} is {populations.get(city_name, 'unknown')}."

def get_country_detail(country_name:str) -> str:
    headers = CaseInsensitiveDict()
    headers["x-rapidapi-host"] = "wft-geo-db.p.rapidapi.com"
    headers["x-rapidapi-key"] = "b95a0f66damsha5c6d0bf2d07954p1d6ed7jsn92d79eb6e8da"
    country_code = {
        "India": "IN",
        "United State": "US"
    }
    cntry_name_shrt_code = country_code[country_name]
    url = f"https://wft-geo-db.p.rapidapi.com/v1/geo/countries/{cntry_name_shrt_code}"
    #print(f"url-- {url}")
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json()["data"]
        callingcode = data["callingCode"]
        currency = data["currencyCodes"][0]
        numberofregion = data["numRegions"]
        flaguri = data["flagImageUri"]
        return f"The currency in {country_name} is {currency} with calling code {callingcode}, number of region {numberofregion} and flag image {flaguri}"
    return f"Couldn't retrieve details for {country_name}."
# 2. Create a dispatch dictionary

function_dispatch = {
    "get_city_weather": get_city_weather,
    "get_city_population": get_city_population,
    "get_country_detail": get_country_detail
}


prompt = "Tell me the weather details of Delhi."
response = model.generate_content(prompt)
parts = response.candidates[0].content.parts
function_call = getattr(parts[0], "function_call", None)
if function_call:
    func_name = function_call.name
    params = function_call.args

    print(f"Model wants to call: {func_name} with args {params}")

    func = function_dispatch.get(func_name)
    if func:
        result = func(**params)  # Unpack the args dictionary
        print("Function result:", result)
    else:
        print(f"No handler defined for function '{func_name}'")
else:
    print("Model response:", response.text)








