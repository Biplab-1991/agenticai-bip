from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage
import json
import re
from langchain.prompts import PromptTemplate

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
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Inject via env or secret
    )

    user_input = state.get("user_input")
    dialog = state.get("dialog", [])

    # Add user input to dialog
    dialog.append({"role": "user", "content": user_input})

    # Initial question → stored as original query
    original_user_input = state.get("original_user_input", user_input)

    # Prompt the LLM with memory + system instruction
    PLANNER_TEMPLATE = """
You are a smart cloud operations and API planning agent. A user will ask questions about cloud resources or problems they are facing.

Your job is to:
- Identify the cloud provider (aws, gcp, azure)
- Identify the user's intent:
  - API action (e.g., get public IP, create VM)
  - Troubleshooting (e.g., "I can't access my instance")
  - Clarification (e.g., user says "public key" — figure out meaning)
- Ask follow-up questions only if needed
- Identify required values (region, instance ID, project ID, etc.)
- Provide helpful suggestions or next steps when applicable
- Construct an executable REST API plan based on the user's need
- Always include the **full API endpoint with https:// scheme**

---

Ambiguity Handling:
- If the user says "public key", ask whether they mean:
  - an SSH key pair
  - a public IP address
  - an encryption key
- If the user mentions "key", clarify if it's an SSH key, access key, encryption key, or something else
- If they ask about "IP", clarify whether they want to describe, allocate, release, or associate it
- If they ask about "access", clarify whether it's about SSH, browser, cloud console, or API access

---

Cloud-Specific Endpoint Formatting:

🟩 GCP (Google Cloud):
- Base URL: `https://compute.googleapis.com/compute/v1`
- Global: `https://compute.googleapis.com/compute/v1/projects/{{project_id}}/global/...`
- Regional: `https://compute.googleapis.com/compute/v1/projects/{{project_id}}/regions/{{region}}/...`
- Zonal: `https://compute.googleapis.com/compute/v1/projects/{{project_id}}/zones/{{zone}}/...`
- Aggregated: `https://compute.googleapis.com/compute/v1/projects/{{project_id}}/aggregated/...`
- Use `oauth2` authentication

🟥 AWS (Amazon Web Services):
- Base URL: `https://ec2.{{region}}.amazonaws.com`
- Format: `https://ec2.{{region}}.amazonaws.com?Action={{ActionName}}&Version=2016-11-15`
- Example: `https://ec2.us-east-1.amazonaws.com?Action=DescribeInstances&Version=2016-11-15`
- Use `sigv4` authentication

🟦 Azure (Microsoft Azure):
- Base URL: `https://management.azure.com`
- Format: `https://management.azure.com/subscriptions/{{subscription_id}}/resourceGroups/{{resource_group}}/providers/Microsoft.Compute/virtualMachines/{{vm_name}}?api-version={{api_version}}`
- Example: `https://management.azure.com/subscriptions/xxx/resourceGroups/yyy/providers/Microsoft.Compute/virtualMachines/myVM?api-version=2023-03-01`
- Use `oauth2` authentication

---

💡 Troubleshooting Intent:
If the user's question indicates a problem (e.g., "can't access instance", "VM not working"):
- Provide 2 or 3 diagnostic suggestions
- Recommend APIs to check instance status, logs, connectivity, or configuration
- Build a REST API plan that can be executed to help resolve the issue (e.g., DescribeInstanceStatus)

---

Output JSON format:

If you need more information from the user:
{{
  "status": "incomplete",
  "question": "Ask the user a precise follow-up question."
}}

If you have everything you need:
{{
  "status": "complete",
  "suggestions": [
    "Optional list of helpful steps or checks for the user"
  ],
  "plan": {{
    "cloud": "aws" | "gcp" | "azure",
    "region": "region-name-if-needed",
    "service": "e.g. ec2, compute, vm, storage",
    "operation": "short human-friendly action like describe_instance, list_vms",
    "resource_id": "resource identifier if applicable",
    "endpoint": "full REST API endpoint (must begin with https://)",
    "http_method": "GET" | "POST",
    "request_parameters": "string or JSON object representing request parameters",
    "auth_type": "sigv4" | "oauth2" | "none"
  }}
}}

⚠️ Only return raw JSON. No markdown. No explanation. No commentary. Just valid, parsable JSON as shown.

User query: {user_input}
"""


##This gives the LLM just enough pattern logic to handle new resources without teaching it every single one.

    cloud_planner_prompt = PromptTemplate(
        input_variables=["user_input"],
        template=PLANNER_TEMPLATE,
    )
    print("llm input state-----------------------------------------------------------------------",state)
    query = state["user_input"]
    followup_context = ""
    if state.get("verification_reason") and "suggested_followup" in state.get("user_input", "").lower():
        followup_context = f"\nNOTE: This is a follow-up action based on prior result. Original query: {original_user_input}\n"

    prompt_text = cloud_planner_prompt.format(user_input=query) + followup_context

    messages = [HumanMessage(content=prompt_text)]
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
