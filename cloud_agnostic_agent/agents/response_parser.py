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

If the response is an error like 404 Not Found, and the issue is a malformed URL or unsupported endpoint, try to:
- Suggest the correct endpoint based on the user's intent and context (project ID, VM name, zone, etc.)
- Recommend the next best step (e.g., retry with corrected URL, switch to another logging API)

Respond in raw JSON like this:
{{
  "status": "not_done",
  "final_output": "Summary or error explanation",
  "suggested_action": "(Optional) New endpoint or fix",
  "followup_question": "(Optional) Ask the user if they want to retry with the suggestion"
}}
"""


    result = llm.invoke([HumanMessage(content=prompt)])

    # Clean and parse response
    raw_text = result.content.strip().lstrip("`json").rstrip("`").strip()
    preserved_keys = [
        "cloud", "region", "zone", "project_id", "subscription_id", "resource_group",
        "service", "operation", "resource_id", "endpoint", "auth_type", "plan"
    ]
    preserved_context = {k: state.get(k) for k in preserved_keys if k in state}
    try:
        parsed = json.loads(raw_text)

        # Inject preserved keys if retry is requested
        if parsed.get("status") == "not_done" and "suggested_action" in parsed:

            return {
                **state,
                **preserved_context,
                "user_input": parsed["suggested_action"],
                "retry": True,
                "verification_reason": "User opted to retry with corrected endpoint from suggested_action.",
                "followup_question": parsed.get("followup_question"),
                "final_output": parsed["final_output"]
            }

        return {
            **state,
            **preserved_context,
            "final_output": parsed["final_output"],
            "suggested_action": parsed.get("suggested_action"),
            "followup_question": parsed.get("followup_question"),
            "status": parsed.get("status", "done")
        }
    except Exception as e:
        return {**state, **preserved_context, "final_output": result.content.strip(), "error_reason": f"Failed to parse LLM output: {str(e)}"}
