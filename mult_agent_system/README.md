# 🌐 LangGraph Multi-Agent System (Weather + Country Info)

This project demonstrates a multi-agent setup using **LangGraph** and **LangChain**, featuring:

- A `supervisor_agent` orchestrated via `create_supervisor`
- Two tool agents:
  - `weather_agent`
  - `country_agent`
- Protocols:
  - `ModelContextProtocol` for full prompt/context
  - `A2AProtocol` for agent-to-agent communication
- Optional: Distributed agent support via `MultiServerMCPClient`

---

## 🏗 Project Structure

multi_agent_system/
├── agents/
│ ├── weather_agent.py # Weather tool using Gemini
│ └── country_agent.py # Country info tool using Gemini
├── supervisor/
│ └── supervisor.py # Supervisor with LangGraph MCP + A2A
├── main.py # CLI loop to interact with the system
├── requirements.txt
└── README.md


---

## 🚀 Setup Instructions

1. **Create a virtual environment** (recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # or venv\\Scripts\\activate on Windows


pip install -r requirements.txt

export GOOGLE_API_KEY="your-google-api-key"


python main.py