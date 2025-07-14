from agents.input_agent import build_input_agent_graph
from agents.intent_agent import build_intent_agent_graph
from agents.supervisor_agent import build_supervisor_agent
from agents.executors.cloud_ops_executor import CloudOpsExecutor
from agents.executors.sysadmin_executor import SysAdminExecutor
from agents.utils.plan_executor import generate_and_execute_once


# STEP 1
def run_input_agent():
    graph = build_input_agent_graph()

    state = {
        "dialog": [],
        "last_input": "",
        "status": "incomplete",
        "final_problem_statement": ""
    }

    while state["status"] != "complete":
        user_input = input("You: ")
        state["last_input"] = user_input
        state = graph.invoke(state)

    return {
        "dialog": state["dialog"],
        "final_problem_statement": state["final_problem_statement"]
    }

# STEP 2
def run_intent_agent(input_output):
    graph = build_intent_agent_graph()

    state = graph.invoke({
        "dialog": input_output["dialog"],
        "final_problem_statement": input_output["final_problem_statement"]
    })

    return state

# STEP 3
def run_supervisor_agent(intent_output):
    graph = build_supervisor_agent()

    state = graph.invoke(intent_output)
    return state

# STEP 4: Execute the plan dynamically
def run_executor(supervisor_output):
    plan = supervisor_output.get("plan", {})

    if not plan:
        print("\n⚠️ No plan to execute.")
        supervisor_output["execution_result"] = {
            "status": "skipped",
            "output": "No plan returned from supervisor.",
            "error": None
        }
        return supervisor_output

    if "endpoint" in plan:
        executor = CloudOpsExecutor()
    elif "commands" in plan:
        executor = SysAdminExecutor(
            ssh_host="YOUR_SSH_HOST",
            username="YOUR_USERNAME",
            private_key_path="PATH_TO_YOUR_PRIVATE_KEY.pem"
        )
    else:
        print("\n⚠️ Unsupported plan type.")
        supervisor_output["execution_result"] = {
            "status": "skipped",
            "output": "Unsupported plan type.",
            "error": None
        }
        return supervisor_output

    return executor.invoke(supervisor_output)


if __name__ == "__main__":
    print("🔍 Input Agent Started...")
    input_output = run_input_agent()

    print("\n🧠 Intent Agent Analyzing...")
    intent_output = run_intent_agent(input_output)

    print("\n🧭 Supervisor Agent Generating Plan and Executing...")
    executed_state = generate_and_execute_once(intent_output)

    print("\n✅ Final Output:")
    print({
        "dialog": executed_state.get("dialog"),
        "final_problem_statement": executed_state.get("final_problem_statement"),
        "flow_type": executed_state.get("flow_type"),
        "documentation": executed_state.get("documentation"),
        "plan": executed_state.get("plan"),
        "execution_result": executed_state.get("execution_result")
    })
