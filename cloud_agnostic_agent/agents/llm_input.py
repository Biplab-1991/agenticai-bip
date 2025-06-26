from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage
import json
import re

def clean_json_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    if text.lower().startswith("json\n"):
        text = text[5:].lstrip()
    return text

def llm_input_agent(state: dict) -> dict:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key=state.get("google_api_key")  # Inject via env or secret
    )

    user_input = state.get("user_input")
    dialog = state.get("dialog", [])

    # Add user input to dialog
    dialog.append({"role": "user", "content": user_input})

    # Initial question → stored as original query
    original_user_input = state.get("original_user_input", user_input)

    # Prompt the LLM with memory + system instruction
    system_prompt = """
You are a smart cloud API planner. A user will ask questions about cloud resources.

You must:
- Identify the cloud provider (aws, gcp, azure)
- Identify the intent (e.g., get public IP, create VM, list buckets)
- Identify required values (region, instance ID, project ID, etc.)
- Decide the right cloud service and REST endpoint
- Choose the HTTP method and auth type

---

Ambiguity Handling:

- If a user says “public key,” ask if they meant “SSH key pair” or “public IP address.”
- If the user says “key,” clarify whether they mean an API key, encryption key, or SSH key.
- If they say “IP,” clarify whether they want to **describe**, **allocate**, **release**, or **associate** an IP.

---

JSON Output Format:

If all info is collected:
{
  "status": "complete",
  "plan": {
    "cloud": "aws" | "gcp" | "azure",
    "region": "...",
    "service": "...",
    "operation": "...",
    "resource_id": "...",
    "endpoint": "...",
    "http_method": "GET" | "POST",
    "request_parameters": "...",
    "auth_type": "sigv4" | "oauth2" | "none"
  }
}

If more info is needed:
{
  "status": "incomplete",
  "question": "Ask the user a precise, minimal follow-up question."
}

Only return JSON. No markdown, no extra explanation.
"""



    messages = [HumanMessage(content=system_prompt)]
    for turn in dialog[-6:]:  # Last few messages
        messages.append(HumanMessage(content=turn["content"]))

    # Invoke LLM
    response = llm.invoke(messages)
    raw_output = clean_json_output(response.content)

    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM output was not valid JSON:\n{raw_output}") from e

    if result.get("status") == "incomplete":
        followup = result.get("question", "Can you clarify?")
        user_reply = input(f"🤖 {followup}\n👉 ")
        return {
            "original_user_input": original_user_input,
            "user_input": user_reply,
            "dialog": dialog + [{"role": "assistant", "content": followup}],
            "retry": True
        }

    if result.get("status") == "complete":
        return {
            "original_user_input": original_user_input,
            "user_input": user_input,
            **result["plan"],
            "plan": result["plan"],
            "dialog": dialog + [{"role": "assistant", "content": raw_output}],
            "retry": False
        }

    raise ValueError(f"Unexpected LLM response:\n{raw_output}")
