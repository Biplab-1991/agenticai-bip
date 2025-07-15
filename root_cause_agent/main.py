from agents.input_agent import build_input_agent_graph
from agents.intent_agent import build_intent_agent_graph
from agents.supervisor_agent import build_supervisor_agent
from agents.executors.cloud_ops_executor import CloudOpsExecutor
from agents.executors.sysadmin_executor import SysAdminExecutor
from agents.utils.plan_executor import generate_and_execute_once
from agents.root_cause_agent import run_root_cause_agent


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
        if state.get("next_question"):
            print(f"🤖 Assistant: {state['next_question']}")

        state["last_input"] = input("You: ")
        state = graph.invoke(state)

        print("🧠 Intermediate Result:", {
            "status": state["status"],
            "final_problem_statement": state.get("final_problem_statement", "")
        })


    return {
        "dialog": state["dialog"],
        "status": state["status"],
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
    print(f"output of input:: {input_output}")

    print("\n🧠 Intent Agent Analyzing...")
    intent_output = run_intent_agent(input_output)
    print(f"output of intent:: {intent_output}")

    print("\n🧭 Supervisor Agent Generating First Plan...")
    first_executed_state = generate_and_execute_once(intent_output)
    #print(f"selected_agent: {first_executed_state.get("selected_agent")}")
    # ✅ Skip root cause loop if fallback agent was chosen
    if first_executed_state.get("selected_agent") == "fallback_agent":
        print("\n⚠️ Fallback agent used — skipping root cause loop.")
        executed_state = first_executed_state
    else:
        print("\n🔁 Root Cause Agent Starting Evaluation Loop...")
        executed_state = run_root_cause_agent(first_executed_state)

    print("\n✅ Final Output:")
    print({
        "dialog": executed_state.get("dialog"),
        "final_problem_statement": executed_state.get("final_problem_statement"),
        "flow_type": executed_state.get("flow_type"),
        "documentation": executed_state.get("documentation"),
        "plans_attempted": executed_state.get("plans_attempted"),
        "execution_results": executed_state.get("execution_results"),
        "status": executed_state.get("status"),
        "root_cause": executed_state.get("root_cause")
    })
