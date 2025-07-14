from langchain_core.runnables import Runnable

class FallbackAgent(Runnable):
    name = "fallback_agent"

    def invoke(self, state: dict, config: dict = None) -> dict:

        state["plan"] = None
        return state
