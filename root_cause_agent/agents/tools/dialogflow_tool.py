def dialogflow_stub(final_problem_statement: str) -> str:
    # Simulate a flow type decision based on final problem statement
    if "network" in final_problem_statement.lower():
        return "guided"
    return "non-guided"
