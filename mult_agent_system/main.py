from supervisor.supervisor import create_supervisor_agent
from langchain_core.messages import HumanMessage

app = create_supervisor_agent()

print("=== AI Supervisor Agent ===")
while True:
    user_input = input("You: ")
    if user_input.strip().lower() in ["exit", "quit"]:
        break

    input_state = {"messages": [HumanMessage(content=user_input)]}
    print("🧪 Input state to app.stream():", input_state)

    for step in app.stream(input_state):
        print("🔁 Step result:", step)

        # Extract the messages properly from supervisor output
        if "supervisor_agent" in step and "messages" in step["supervisor_agent"]:
            last_message = step["supervisor_agent"]["messages"][-1]
            print("🤖 AI:", last_message.content)
