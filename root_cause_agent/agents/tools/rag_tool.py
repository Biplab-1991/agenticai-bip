def rag_stub(final_problem_statement: str) -> list:
    # Simulate RAG response
    if "timeout" in final_problem_statement.lower():
        return [
            "Check if the service is running.",
            "Restart the application.",
            "Check load balancer logs."
        ]
    return []  # Simulate fallback scenario
