from langchain_core.runnables import Runnable

class FallbackAgent(Runnable):
    def invoke(self, state: dict) -> dict:
        state["plan"] = None
        return state
