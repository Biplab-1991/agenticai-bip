from agents.cloudops_agent import create_cloudops_agent
from langchain.schema import HumanMessage

app = create_cloudops_agent()

print("=== CloudOps Agent ===")
print("Ask me to manage AWS: 'List EC2', 'Reboot i-123...', 'List S3 buckets'")
print("Type 'exit' to quit.\n")

conversation = []

while True:
    user_input = input("You: ").strip()
    if user_input.lower() in ["exit", "quit"]:
        print("Goodbye!")
        break

    # Add user input to conversation history
    conversation.append(HumanMessage(content=user_input))

    try:
        final_response = None
        for step in app.stream({"messages": conversation}):
            for value in step.values():
                if isinstance(value, dict) and "messages" in value:
                    messages = value["messages"]
                    if messages:
                        final_response = messages[-1]
                        conversation.append(final_response)  # Track LLM's last reply

        if final_response:
            print(f"\nCloudOps Agent: {final_response.content}")
        else:
            print("\nCloudOps Agent: I didn’t understand your request.")
    except Exception as e:
        print(f"\nError: {e}")
