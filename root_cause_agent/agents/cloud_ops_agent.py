from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage

# Initialize Gemini
gemini = ChatGoogleGenerativeAI(model="gemini-pro")

class CloudOpsAgent(Runnable):
    def invoke(self, state: dict) -> dict:
        prompt = f"""
You are a cloud operations planning agent.

Your task is to extract an executable REST API plan using the details provided below.

Input:
- Problem: {state['final_problem_statement']}
- Flow type: {state['flow_type']}
- Documentation steps:
{state['documentation']}

Use this context to identify:
- The cloud provider (aws, gcp, azure)
- The service being operated on (e.g., ec2, compute, vm)
- The operation being attempted (e.g., describe_instance, start_vm)
- The resource ID if applicable
- The full REST API endpoint (must begin with https://)
- Required request parameters
- The appropriate HTTP method
- Authentication type (sigv4, oauth2, or none)

Respond only in this format:

{{
  "plan": {{
    "cloud": "...",
    "region": "...",
    "service": "...",
    "operation": "...",
    "resource_id": "...",
    "endpoint": "https://...",
    "http_method": "GET" | "POST",
    "request_parameters": "...",
    "auth_type": "sigv4" | "oauth2" | "none"
  }}
}}
"""


        response = gemini.invoke([HumanMessage(content=prompt)])
        try:
            plan_json = eval(response.content)  # You may replace this with json.loads() + cleanup if needed
            state["plan"] = plan_json["plan"]
        except Exception as e:
            state["plan"] = {
                "error": "Failed to parse response from Gemini",
                "details": str(e),
                "raw_output": response.content
            }

        return state
