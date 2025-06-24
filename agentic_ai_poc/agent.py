from google.adk.agents import Agent

# root_agent = Agent(
#     model='gemini-2.0-flash-001',
#     name='root_agent',
#     description='A helpful assistant for user questions.',
#     instruction='Answer user questions to the best of your knowledge',
# )

basic_agent = Agent(   
    name="basic_agent",
    model="gemini-2.0-flash",
    description="A simple agent that answers questions",
    instruction="""You are a helpful stock market assistant. Be concise.If you don't know something, just say no."""

)

root_agent = basic_agent
