from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import Runnable
from langchain_core.messages import HumanMessage

# Initialize Gemini
gemini = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Inject via env or secret
    )

class SysAdminAgent(Runnable):
    name = "sysadmin_agent"

    def invoke(self, state: dict, config: dict = None) -> dict:

        prompt = f"""
You are a Linux/Cloud SysAdmin assistant.

Your job is to generate a shell-based troubleshooting plan (not a REST API) based on the given context.

Context:
- Final problem statement: {state['final_problem_statement']}
- Flow type: {state['flow_type']}
- Documentation steps:
{state['documentation']}

Your output must include:
- The cloud and service (e.g. ec2, vm, ssh)
- The operation (e.g. ssh_login_check, check_daemon, etc.)
- Optional resource_id (e.g. VM ID or hostname)
- A list of Linux/SSH commands that would help troubleshoot the issue
- The authentication method (ssh or none)

Respond only in this exact format:

{{
  "plan": {{
    "cloud": "aws" | "gcp" | "azure",
    "region": "optional region name",
    "service": "e.g. ec2, compute, vm, ssh",
    "operation": "short human-friendly label like check_ssh_login",
    "resource_id": "instance ID or hostname if applicable",
    "commands": [
      "ssh ec2-user@<ip-address>",
      "sudo systemctl status sshd",
      "cat /var/log/auth.log"
    ],
    "auth_type": "ssh" | "none"
  }}
}}
"""

        response = gemini.invoke([HumanMessage(content=prompt)])

        try:
            plan_json = eval(response.content)  # Replace with safer json.loads() + cleanup in production
            state["plan"] = plan_json["plan"]
        except Exception as e:
            state["plan"] = {
                "error": "Failed to parse plan from Gemini",
                "details": str(e),
                "raw_output": response.content
            }

        return state
