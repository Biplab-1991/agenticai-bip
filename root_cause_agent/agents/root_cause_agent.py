import copy
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from agents.utils.plan_executor import generate_and_execute_once

# Gemini LLM setup
llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"  # Inject via env or secret
    )


def ask_gemini_if_resolved(state, documentation, plans_attempted, execution_results):
    steps_left = [
        step for step in documentation
        if step not in [p.get("operation") for p in plans_attempted]
    ]

    dialog = "\n".join(state.get("dialog", []))
    final_problem = state.get("final_problem_statement", "")

    summary = "\n".join(
        f"{i+1}. Ran: {plan.get('operation')} → Output: {res.get('output')[:300]}"
        for i, (plan, res) in enumerate(zip(plans_attempted, execution_results))
    )

    prompt = f"""
You are a root cause analysis expert.

Problem: {final_problem}
Conversation: {dialog}

Previous attempts:
{summary}

Remaining troubleshooting steps: {steps_left}

Question:
Based on the previous steps and output, has the issue been resolved?
If not, which step should we try next?

Respond in JSON with:
- status: "complete" or "incomplete"
- root_cause: explanation or null
- next_step: string (from remaining steps) or null
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        parsed = json.loads(response.content)
        return parsed
    except Exception as e:
        return {
            "status": "incomplete",
            "root_cause": None,
            "next_step": steps_left[0] if steps_left else None,
            "error": str(e)
        }


def run_root_cause_agent(initial_state: dict) -> dict:
    documentation = initial_state.get("documentation", [])
    state = copy.deepcopy(initial_state)
    plans_attempted = []
    execution_results = []
    gemini_evals = []

    status = "incomplete"
    root_cause = None

    while status != "complete":
        print(f"\n🔁 Generating next plan...")

        print("\n🔁 Generating and executing next plan...")
        state = generate_and_execute_once(state)

        plan = state.get("plan")
        result = state.get("execution_result")

        if not plan or not result:
            print("⚠️ Plan or execution missing. Exiting.")
            break

        plans_attempted.append(plan)
        execution_results.append(result)

        # Evaluate using Gemini
        gemini_result = ask_gemini_if_resolved(
            state,
            documentation,
            plans_attempted,
            execution_results
        )
        gemini_evals.append(gemini_result)

        # Status check
        status = gemini_result.get("status", "incomplete")
        root_cause = gemini_result.get("root_cause")

        # Stop if complete or no next step
        if status == "complete" or not gemini_result.get("next_step"):
            break

        # Otherwise, pass next_step hint to SupervisorAgent for next loop
        state["next_step"] = gemini_result["next_step"]

    # Final aggregated result
    return {
        "dialog": state.get("dialog"),
        "final_problem_statement": state.get("final_problem_statement"),
        "flow_type": state.get("flow_type"),
        "documentation": documentation,
        "plans_attempted": plans_attempted,
        "execution_results": execution_results,
        "gemini_evaluations": gemini_evals,
        "status": status,
        "root_cause": root_cause
    }
