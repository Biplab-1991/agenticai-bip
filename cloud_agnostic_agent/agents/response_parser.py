from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage
import json

def response_parser_agent(state: dict) -> dict:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Replace or inject via env/secret
    )

    # Get original query and cloud response
    query = state.get("original_user_input", "")
    raw_response = state.get("response", {})

    # Make sure it's a dict
    if isinstance(raw_response, str):
        try:
            raw_response = json.loads(raw_response)
        except json.JSONDecodeError:
            pass  # Keep as-is

    prompt = f"""
You are a helpful cloud assistant.

Given:
- A user query: "{query}"
- A JSON response from a cloud API: {json.dumps(raw_response, indent=2)}

Extract the single most relevant answer to the user query.

Only return the final answer — do not include explanations or markdown.
"""

    result = llm.invoke([HumanMessage(content=prompt)])

    return {
        "final_output": result.content.strip()
    }
