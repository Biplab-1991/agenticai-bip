# 🔍 Root Cause Agent System (Cloud-Agnostic)

This project is an intelligent, agentic system designed to troubleshoot cloud problems (AWS, GCP, Azure) using a chain of agents powered by [LangGraph](https://github.com/langchain-ai/langgraph), [Gemini](https://ai.google.dev/), and real API/SSH execution logic.

---

## 🧠 Architecture Overview

```
┌────────────┐
│ User Input │
└─────┬──────┘
      ▼
┌──────────────┐
│ Input Agent  │  ← Interactively collects dialog + problem
└─────┬────────┘
      ▼
┌───────────────┐
│ Intent Agent  │  ← Identifies flow type + fetches documentation
└─────┬─────────┘
      ▼
┌────────────────┐
│ SupervisorAgent│  ← Routes to CloudOps, SysAdmin, or Fallback
└─────┬──────────┘
      ▼
┌────────────┐        ┌──────────────┐
│ Executor   │◄──────▶│ PlanExecutor │ ← Reusable executor engine
└────────────┘        └──────────────┘
      ▼
┌────────────────┐
│ RootCauseAgent │ ← Uses Gemini to loop until root cause is found
└────────────────┘
```

---

## 🧩 Agents Overview

### 1. `InputAgent`
- Collects user input step-by-step
- Returns:
  ```json
  {
    "dialog": [...],
    "final_problem_statement": "...",
    "status": "complete"
  }
  ```

### 2. `IntentAgent`
- Identifies:
  - Flow type: guided / non-guided
  - Documentation: list of troubleshooting steps
- Uses Dialogflow + RAG (stubbed initially)

### 3. `SupervisorAgent`
- Uses `LangGraph`'s `create_supervisor` to route intelligently to:
  - `CloudOpsAgent`: builds cloud API plans
  - `SysAdminAgent`: builds SSH command plans
  - `FallbackAgent`: returns documentation only

### 4. `RootCauseAgent`
- Uses `Gemini` to:
  - Check if previous executions solved the issue
  - Select next step from documentation
  - Loop until root cause is found or steps exhausted

---

## ⚙️ Executors

### ✅ CloudOpsExecutor
- Executes real REST API plans
- Supports:
  - `sigv4` (AWS)
  - `oauth2` (GCP, Azure)

### ✅ SysAdminExecutor
- Executes SSH commands using Paramiko

---

## 🔁 Plan Execution Utility

### File: `agents/utils/plan_executor.py`

```python
def generate_and_execute_once(state: dict) -> dict:
```

- Runs `SupervisorAgent` to generate the plan
- Executes via the correct executor (REST or SSH)
- Returns updated state with:
  - `plan`
  - `execution_result`

This utility is reused by both:
- `main.py` (for one-shot planning + execution)
- `RootCauseAgent` (for iterative troubleshooting)

---

## ▶️ Running the System

In `main.py`, we chain the agents:

```python
input_output = run_input_agent()
intent_output = run_intent_agent(input_output)
executed_state = generate_and_execute_once(intent_output)
```

Or use the full `RootCauseAgent` loop:

```python
from agents.root_cause_agent import run_root_cause_agent

final_result = run_root_cause_agent(input_output)
```

---

## 🧪 Final Output from `RootCauseAgent`

```json
{
  "dialog": [...],
  "final_problem_statement": "...",
  "flow_type": "guided",
  "documentation": [...],
  "plans_attempted": [...],
  "execution_results": [...],
  "gemini_evaluations": [...],
  "status": "complete",
  "root_cause": "SSH key missing in metadata"
}
```

---

## ✅ Setup Notes

- Requires:
  - LangGraph
  - LangChain
  - Google Generative AI SDK
  - Paramiko
  - Requests
- Create `.env` or secret manager bindings for:
  - GCP Access Token logic
  - AWS Credentials

---

## 🚧 TODO

- [ ] Add real Dialogflow and RAG tool integrations
- [ ] Store root cause history in a DB
- [ ] Add retry logic and circuit breaker
- [ ] Secure SSH credential handling via vault

---

