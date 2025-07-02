from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage
import json

def verify_completion_agent(state: dict) -> dict:
    preserved_keys = [
        "cloud", "region", "zone", "project_id", "subscription_id", "resource_group",
        "service", "operation", "resource_id", "endpoint", "auth_type", "plan"
    ]
    preserved_context = {k: v for k in preserved_keys if (v := state.get(k)) is not None}

    original_user_input = state.get("original_user_input") or state.get("user_input") or ""
    assistant_answer = state.get("final_output") or state.get("plan") or state.get("response") or ""

    if not original_user_input:
        return {
            **state,
            **preserved_context,
            "status": "not_done",
            "retry": True,
            "user_input": "Hello! Can you please rephrase or describe your cloud task again?",
            "verification_reason": "Missing original user query — cannot evaluate the answer."
        }

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        google_api_key="AIzaSyCN0Esg5nooULYxSO7EO82RTmacXnwjzx0"
    )

    system_prompt = f"""
You are evaluating whether the assistant's answer resolves the user's cloud request.

Here is the conversation:

User asked: {original_user_input}
Assistant replied: {assistant_answer}

Your job:
- If the assistant answer is correct and solves the user’s request, return:
{{
  "status": "done"
}}

- If more action is needed, you must return:
{{
  "status": "not_done",
  "reason": "Brief reason why this is incomplete",
  "suggested_followup": "Concrete next user command (e.g., 'start the VM')",
  "followup_question": "Yes/no question to ask user if they want to do it"
}}

Do not skip any fields.
"""

    attempts = state.get("verification_attempts", 0) + 1

    if attempts > 5:
        print("❗ Verification loop limit exceeded. Ending to prevent recursion.")
        return {
            **state,
            **preserved_context,
            "status": "done",
            "retry": False,
            "user_input": original_user_input,
            "verification_reason": "Exceeded verification retry limit.",
            "verification_attempts": attempts
        }

    try:
        response = llm.invoke([HumanMessage(content=system_prompt)])
        parsed = json.loads(response.content.strip())

        print(f"\n🔍 [verify_completion_agent] Attempt #{attempts}")
        print(f"User: {original_user_input}")
        print(f"🤖 Assistant: {assistant_answer}")

        # If task is complete
        if parsed.get("status") == "done":
            return {
                **state,
                **preserved_context,
                "status": "done",
                "retry": False,
                "user_input": original_user_input,
                "verification_reason": parsed.get("reason", "Verified as complete."),
                "verification_attempts": attempts
            }

        # Follow-up logic
        reason = parsed.get("reason", "Assistant output incomplete.")
        suggestion = parsed.get("suggested_followup")
        followup_question = parsed.get("followup_question") or f"Do you want me to try: '{suggestion}'?"

        if not suggestion:
            return {
                **state,
                **preserved_context,
                "status": "not_done",
                "retry": True,
                "user_input": "Please clarify your cloud request.",
                "verification_reason": "Missing suggested follow-up — cannot continue automatically.",
                "verification_attempts": attempts
            }

        print(f"💡 {reason}")
        print(f"🛠 {followup_question}")
        # Check if plan matches suggested action
        current_plan_text = json.dumps(state.get("plan") or {}).lower()
        suggestion_text = (suggestion or "").lower()

        # Heuristically check if the suggestion has already been planned
        plan_matches_suggestion = suggestion_text and suggestion_text in current_plan_text

        # Decide next action
        next_action = "execute_request" if plan_matches_suggestion else "llm_input"
        confirm = input("➡️  Do you want me to do this? (yes/no): ").strip().lower()


        if confirm in {"yes", "y"}:
            return {
                **state,
                **preserved_context,
                "status": "not_done",
                "retry": True,
                "user_input": suggestion,
                "original_user_input": original_user_input,
                "followup_question": followup_question,
                "followup_action": suggestion,
                "next_action": next_action,
                "verification_reason": reason,
                "verification_attempts": attempts,
                "final_output": assistant_answer
            }

        else:
            return {
                **state,
                **preserved_context,
                "status": "done",
                "retry": False,
                "user_input": original_user_input,
                "verification_reason": "User declined the suggestion.",
                "verification_attempts": attempts,
                "final_output": assistant_answer
            }

    except Exception as e:
        return {
            **state,
            **preserved_context,
            "status": "not_done",
            "retry": True,
            "user_input": original_user_input or "Please retry",
            "verification_reason": f"Parsing failed: {str(e)}",
            "verification_attempts": attempts
        }
