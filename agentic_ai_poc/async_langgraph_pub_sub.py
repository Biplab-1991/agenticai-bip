import asyncio
import json
import operator
from typing import Annotated, List, TypedDict

from google.cloud import pubsub_v1
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import START, END, StateGraph

# --- Configuration ---
# IMPORTANT: Replace with your actual Google Cloud Project ID
PROJECT_ID = "spiritual-verve-461804-h5" # e.g., ""

# Pub/Sub Topic and Subscription Names
# This topic is where the PublishingAgent will send its output.
PUBLISHING_AGENT_OUTPUT_TOPIC = "agent-a-output"
# This subscription will be used by our async Pub/Sub listener utility.
# Messages received here will trigger the ListeningAgent.
LISTENING_AGENT_INPUT_SUBSCRIPTION = "agent-a-output-sub"

# --- Pub/Sub Helper Classes ---

class AsyncPubSubPublisher:
    """
    Asynchronous client for publishing messages to Google Pub/Sub.
    """
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.publisher = pubsub_v1.PublisherClient()

    async def publish_message(self, topic_id: str, data: bytes, **attributes):
        """
        Publishes a message to the specified Pub/Sub topic.
        Args:
            topic_id: The ID of the Pub/Sub topic.
            data: The message payload as bytes.
            attributes: Optional key-value attributes for the message.
        """
        topic_path = self.publisher.topic_path(self.project_id, topic_id)
        future = self.publisher.publish(topic_path, data, **attributes)

        try:
            await asyncio.to_thread(future.result)
            print(f"[{topic_id}] Published message. Message ID: {future.result()}")
        except Exception as e:
            print(f"[{topic_id}] Failed to publish message: {e}")
            raise # Re-raise to signal failure

class AsyncPubSubSubscriber:
    """
    Asynchronous client for subscribing to messages from Google Pub/Sub.
    Handles message reception and dispatches to a callback function.
    """
    def __init__(self, project_id: str, subscription_id: str, callback_fn, loop: asyncio.AbstractEventLoop):
        self.project_id = project_id
        self.subscription_id = subscription_id
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(self.project_id, self.subscription_id)
        self.callback_fn = callback_fn
        self.streaming_pull_future = None
        self.loop = loop # Store the event loop passed from the main thread

    def _message_callback(self, message: pubsub_v1.subscriber.message.Message):
        """
        Internal callback for Pub/Sub messages.
        This runs in a separate thread managed by the Pub/Sub client.
        It dispatches the message to the user-defined async callback on the main event loop.
        """
        try:
            # Use the stored event loop from the main thread to schedule the coroutine
            asyncio.run_coroutine_threadsafe(
                self.callback_fn(message.data.decode('utf-8'), dict(message.attributes)), self.loop
            )
            message.ack() # Acknowledge the message once it's scheduled for processing
        except Exception as e:
            print(f"Error in _message_callback (message not acknowledged): {e}")

    async def start_listening(self):
        """Starts listening for messages on the configured subscription."""
        print(f"Listening for messages on {self.subscription_path}...")
        self.streaming_pull_future = self.subscriber.subscribe(
            self.subscription_path, callback=self._message_callback
        )
        try:
            await asyncio.to_thread(self.streaming_pull_future.result)
        except asyncio.CancelledError:
            print(f"Subscriber for {self.subscription_path} cancelled.")
        except Exception as e:
            print(f"Subscriber error for {self.subscription_path}: {e}")
        finally:
            self.streaming_pull_future.cancel()
            await asyncio.to_thread(self.subscriber.close)
            print(f"Subscriber for {self.subscription_path} stopped.")

    async def stop_listening(self):
        """Stops the Pub/Sub subscriber."""
        if self.streaming_pull_future:
            print(f"Stopping subscriber for {self.subscription_path}...")
            self.streaming_pull_future.cancel()
            await asyncio.sleep(2) # Give it a moment to shut down gracefully
            print("Subscriber shutdown initiated.")


# --- LangGraph Definition ---

class AgentState(TypedDict):
    """
    Represents the shared state of our graph.
    """
    messages: Annotated[List[BaseMessage], operator.add]
    # We will use 'last_pubsub_message' to store the payload from Pub/Sub
    # before it's processed by the ListeningAgent.
    last_pubsub_message: dict
    workflow_status: str

# Initialize Pub/Sub Publisher Client
pubsub_publisher = AsyncPubSubPublisher(PROJECT_ID)

async def publishing_agent_node(state: AgentState):
    """
    This agent simulates performing a task and then publishes its result to Pub/Sub.
    It doesn't care about what happens next.
    """
    print(f"\n--- PublishingAgent ({state['workflow_status']}) ---")
    initial_request = state['messages'][0].content if state['messages'] else "No initial request."
    print(f"PublishingAgent received initial request: '{initial_request}'")

    # Simulate complex processing
    processed_data = f"Document '{initial_request[:20]}...' processed. Summary generated."
    agent_output_message = HumanMessage(content=processed_data, name="PublishingAgent")

    # Prepare data to send via Pub/Sub
    pubsub_payload = {
        "workflow_id": "workflow_XYZ_456", # A unique ID to track a specific workflow instance
        "origin_agent": "PublishingAgent",
        "processed_result": processed_data,
        "next_action": "analyze_summary" # Hint for the next stage
    }
    encoded_payload = json.dumps(pubsub_payload).encode("utf-8")

    # Publish the message
    await pubsub_publisher.publish_message(PUBLISHING_AGENT_OUTPUT_TOPIC, encoded_payload)

    print("PublishingAgent finished its immediate task and published to Pub/Sub.")
    return {
        "messages": [agent_output_message],
        "workflow_status": "published_to_pubsub",
        "last_pubsub_message": {} # Clear, as this agent published it
    }

async def listening_agent_node(state: AgentState):
    """
    This agent is designed to process data that arrives via Pub/Sub.
    It takes the 'last_pubsub_message' from the state.
    """
    print(f"\n--- ListeningAgent ({state['workflow_status']}) ---")
    pubsub_data = state.get('last_pubsub_message', {})
    processed_result = pubsub_data.get('processed_result', 'No processed result found in Pub/Sub data.')
    origin_agent = pubsub_data.get('origin_agent', 'unknown')
    next_action = pubsub_data.get('next_action', 'no_action_specified')

    print(f"ListeningAgent received data from '{origin_agent}' via Pub/Sub: '{processed_result}'")
    print(f"Suggested next action: '{next_action}'")

    # Simulate further analysis
    analysis_result = f"ListeningAgent performed analysis on '{processed_result}'. Confirmed action: {next_action}."
    agent_output_message = HumanMessage(content=analysis_result, name="ListeningAgent")

    print("ListeningAgent completed its processing.")
    return {
        "messages": [agent_output_message],
        "workflow_status": "listening_agent_completed",
        "last_pubsub_message": {} # Clear after processing
    }

# --- LangGraph Workflow Definition ---
# This graph will represent the workflow that starts with PublishingAgent
# and can be separately triggered for ListeningAgent.

publishing_workflow = StateGraph(AgentState)
publishing_workflow.add_node("publishing_agent", publishing_agent_node)
publishing_workflow.add_edge(START, "publishing_agent")
publishing_workflow.add_edge("publishing_agent", END) # PublishingAgent's graph run completes here

# Compile the graph for the publishing part
publishing_app = publishing_workflow.compile()

# We can define a separate graph or entry point for the ListeningAgent
# This emphasizes that it's triggered externally via Pub/Sub.
# For simplicity, we'll use the same `AgentState` and define the ListeningAgent as
# a node within a graph that can be invoked directly.
listening_workflow = StateGraph(AgentState)
listening_workflow.add_node("listening_agent", listening_agent_node)
# The listening agent is intended to be triggered directly by the Pub/Sub callback,
# so we can make it the START of its own conceptual subgraph/workflow when invoked this way.
listening_workflow.add_edge(START, "listening_agent")
listening_workflow.add_edge("listening_agent", END)
listening_app = listening_workflow.compile()


# --- Pub/Sub Callback to Trigger ListeningAgent ---

async def pubsub_trigger_listening_agent_callback(message_data: str, attributes: dict):
    """
    This callback is executed when a message is received from Pub/Sub.
    It parses the message and invokes the 'listening_app' (ListeningAgent).
    """
    print(f"\n--- Pub/Sub Listener (Triggering ListeningAgent) ---")
    print(f"Received raw message data: {message_data}")
    print(f"Received attributes: {attributes}")

    try:
        parsed_payload = json.loads(message_data)
        workflow_id = parsed_payload.get("workflow_id", "no_workflow_id")

        print(f"Parsed payload for workflow ID: {workflow_id}")

        # Construct the initial state for the ListeningAgent's workflow.
        # The key is to pass the Pub/Sub data in a way the agent can access it.
        initial_state_for_listening_agent = {
            "messages": [HumanMessage(content=f"Pub/Sub message received for workflow {workflow_id}", name="PubSubTrigger")],
            "workflow_status": "triggered_by_pubsub",
            "last_pubsub_message": parsed_payload # Pass the entire parsed payload
        }

        print(f"Invoking ListeningAgent workflow for workflow ID: {workflow_id}")
        # Invoke the separate compiled graph for the listening agent
        final_state_listening_agent = await listening_app.ainvoke(initial_state_for_listening_agent)
        print(f"ListeningAgent workflow for {workflow_id} completed. Final state:\n{final_state_listening_agent}")

    except json.JSONDecodeError:
        print(f"ERROR: Could not parse Pub/Sub message data as JSON: {message_data}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in Pub/Sub callback triggering ListeningAgent: {e}")

# --- Main Application Execution ---

# ... (rest of your code remains the same) ...

async def main():
    print("Starting asynchronous LangGraph agents with explicit Pub/Sub integration...")

    main_loop = asyncio.get_running_loop()

    pubsub_subscriber = AsyncPubSubSubscriber(
        PROJECT_ID, LISTENING_AGENT_INPUT_SUBSCRIPTION, pubsub_trigger_listening_agent_callback, main_loop
    )

    # Start the subscriber task.
    subscriber_task = asyncio.create_task(pubsub_subscriber.start_listening())

    # --- CRITICAL CHANGE HERE ---
    # Give the subscriber a moment to establish its connection and start listening.
    # A small delay (e.g., 2-5 seconds) is usually sufficient for local testing.
    # In a real production system, you might use more robust health checks or
    # a readiness probe, but for a simple script, a small sleep works.
    print("Giving subscriber a moment to warm up...")
    await asyncio.sleep(5) # Wait for 5 seconds

    # --- Step 1: Trigger the PublishingAgent ---
    print("\n--- Triggering PublishingAgent workflow ---")
    initial_publishing_input = {
        "messages": [HumanMessage(content="Process financial report 2025-Q1.")],
        "workflow_status": "initial_request",
        "last_pubsub_message": {}
    }
    try:
        final_state_publishing_agent = await publishing_app.ainvoke(initial_publishing_input)
        print("\n--- PublishingAgent workflow completed and published to Pub/Sub ---")
        print(f"Final state of PublishingAgent workflow:\n{final_state_publishing_agent}")
    except Exception as e:
        print(f"ERROR: PublishingAgent workflow failed: {e}")

    print("\nMain application running, waiting for Pub/Sub messages to activate ListeningAgent...")

    try:
        await subscriber_task
    except asyncio.CancelledError:
        print("Main application loop cancelled.")
    finally:
        await pubsub_subscriber.stop_listening()
        print("Application shutting down.")

if __name__ == "__main__":
    print("Setting up and running the async agents...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"An unexpected error occurred during application execution: {e}")
