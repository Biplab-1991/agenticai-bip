# ☁️ Cloud-Agnostic LangGraph Multi-Agent System

## 🔧 Setup

1. Add your AWS credentials JSON in GCP Secret Manager as `aws-credentials`.
2. Add your GCP Service Account JSON as secret `gcp-sa-key`.
3. Set:
   ```bash
   export GCP_PROJECT_ID=your-project-id
pip install -r requirements.txt
python main.py
