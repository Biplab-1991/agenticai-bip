import operator
from typing import Annotated, TypedDict, Literal

# Import necessary components from langchain_core and langgraph
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END, START
from langgraph.types import Command # Import Command for explicit state updates
from langchain_google_genai import ChatGoogleGenerativeAI

# --- 1. Define the Graph State ---
# The state is a shared object that all agents in the graph can read from and write to.
# This is the primary mechanism for agents to communicate and pass information.
class AgentState(TypedDict):
    """
    Represents the state of our multi-agent conversation.

    Attributes:
        messages: A list of all messages (user input, AI responses, tool outputs).
                  Annotated with operator.add to ensure new messages are appended.
        research_findings: A string to store the output from the research agent.
        summary_output: A string to store the output from the summary agent.
        # Add a flag to indicate if research was successfully done, for clearer logic
        research_done: bool
    """
    messages: Annotated[list[BaseMessage], operator.add]
    research_findings: str
    summary_output: str
    research_done: bool

# --- 2. Create a Mock LLM (for demonstration) ---
# In a real application, you would replace this with an actual LLM
# like ChatOpenAI, ChatAnthropic, etc., by importing from langchain_openai, etc.
# Initialize 
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", google_api_key="AIzaSyBo4a3W2yzFg_YMdIBSYgKIBn6JDnf2Gc4")

# --- 3. Define the Agents (Nodes in the Graph) ---

def research_agent(state: AgentState) -> Command[Literal["summarizer"]]:
    """
    Agent A: Simulates performing research based on the user's initial query.
    It updates the 'research_findings' in the shared state and explicitly
    commands the transition to the summarizer.
    """
    print("\n--- AGENT A: RESEARCHER ---")
    user_query = state["messages"][-1].content # Get the latest user message

    # Simulate LLM processing for research
    research_prompt = f"Perform research about {user_query}."
    llm_response = llm.invoke([HumanMessage(content=research_prompt)])
    findings = llm_response.content

    print(f"Researcher output: {findings}")

    # Explicitly return a Command to update the state and transition to the next node
    return Command(
        goto="summarizer", # Direct transition to the summarizer node
        update={
            "messages": [AIMessage(content=f"Research complete. Findings: {findings}")],
            "research_findings": findings,
            "research_done": True # Set flag indicating research is complete
        }
    )

def summary_agent(state: AgentState) -> Command[Literal[END]]:
    """
    Agent B: Simulates summarizing the 'research_findings' provided by Agent A.
    It updates the 'summary_output' in the shared state and explicitly
    commands the end of the workflow.
    """
    print("\n--- AGENT B: SUMMARIZER ---")
    research_findings = state["research_findings"] # Get findings from the shared state

    if not state.get("research_done"): # Check if research was actually done
        error_message = "Error: Research was not successfully completed. Cannot summarize."
        print(error_message)
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=error_message)], "summary_output": "Error: Missing research findings."}
        )

    # Simulate LLM processing for summarization
    summary_prompt = f"Summarize the following findings: {research_findings}"
    llm_response = llm.invoke([HumanMessage(content=summary_prompt)])
    summary = llm_response.content

    print(f"Summarizer output: {summary}")

    # Explicitly return a Command to update the state and end the graph
    return Command(
        goto=END, # End the workflow
        update={
            "messages": [AIMessage(content=f"Summary complete. Here is the summary: {summary}")],
            "summary_output": summary
        }
    )

# --- 4. Build the LangGraph Workflow ---

# Initialize the StateGraph with our defined state schema
workflow = StateGraph(AgentState)

# Add nodes for each agent function
workflow.add_node("researcher", research_agent) # Agent A
workflow.add_node("summarizer", summary_agent)  # Agent B

# Define the entry point of the graph. The first node to be executed.
workflow.set_entry_point("researcher") # Start with the researcher agent

# Define the edges (how agents are linked and communicate flow)
# Agent A (researcher) always transitions to Agent B (summarizer)
# The transition is now implicitly handled by the Command(goto="summarizer") in research_agent.
# We still add a "default" edge here for clarity if direct Command.goto wasn't used for ALL paths.
# In this specific setup, since research_agent always calls Command(goto="summarizer"),
# this add_edge is technically redundant but good for explicit graph definition.
workflow.add_edge("researcher", "summarizer")


# Agent B (summarizer) always ends the workflow
# The transition is now implicitly handled by the Command(goto=END) in summary_agent.
workflow.add_edge("summarizer", END)

# Compile the graph
app = workflow.compile()

# --- 5. Run the System ---

print("LangGraph Two-Agent Communication Example (Revised) Initiated.")
print("Enter a topic for research (e.g., 'artificial intelligence').")
print("Type 'exit' to quit.")

while True:
    user_input = input("\nUser: ")
    if user_input.lower() == 'exit':
        print("Exiting conversation. Goodbye!")
        break

    # Prepare the initial state with the user's message
    initial_state = {
        "messages": [HumanMessage(content=user_input)],
        "research_findings": "", # These will be populated by the agents
        "summary_output": "",
        "research_done": False # Initial state for the flag
    }

    print("\n--- Running LangGraph Workflow ---")
    # Invoke the graph and stream the output to see each step
    # The 'stream' method yields the state at each node execution.
    for s in app.stream(initial_state):
        if "__end__" not in s:
            # Print the state as it evolves through the nodes
            print(s)
        else:
            # When the END node is reached, print the final output
            final_messages = s["__end__"]["messages"]
            final_summary = s["__end__"]["summary_output"]
            print("\n--- FINAL RESULT ---")
            print(f"Full conversation history:")
            for msg in final_messages:
                print(f"  {msg.type.capitalize()}: {msg.content}")
            print(f"\nFinal Summary from Summarizer Agent: {final_summary}")
            print("--------------------")

 