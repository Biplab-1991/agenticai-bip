from agents.supervisor_agent import build_supervisor_agent
from agents.executors.cloud_ops_executor import CloudOpsExecutor
from agents.executors.sysadmin_executor import SysAdminExecutor

def generate_and_execute_once(state: dict) -> dict:
    """
    Run supervisor agent to generate a plan and execute it with the appropriate executor.

    Returns the updated state with `plan` and `execution_result` included.
    """

    #print(f"state in plan executor::: {state}")
    # Step 1: Generate plan
    supervisor = build_supervisor_agent(state)
    result = supervisor.invoke(state, config={"return_intermediate_steps": True})
    #result = build_supervisor_agent(state)
    #print(f"result in plan executor:: {result}")

    selected_agent = None

    messages = result.get("messages", [])
    if messages:
        message = messages[0]
        if hasattr(message, "content"):
            selected_agent = message.content.strip()

    # ✅ Store in state
    state["selected_agent"] = selected_agent


    plan = state.get("plan")
    if not plan:
        state["execution_result"] = {
            "status": "skipped",
            "output": "Supervisor failed to generate plan.",
            "error": None
        }
        return state

    # Step 2: Choose executor
    if "endpoint" in plan:
        executor = CloudOpsExecutor()
    elif "commands" in plan:
        executor = SysAdminExecutor(
            ssh_host="YOUR_SSH_HOST",
            username="YOUR_USERNAME",
            private_key_path="PATH_TO_KEY.pem"
        )
    else:
        state["execution_result"] = {
            "status": "skipped",
            "output": "Unsupported plan format.",
            "error": None
        }
        return state

    # Step 3: Execute plan
    state = executor.invoke(state)
    return state
