# CloudOps Agent (LangGraph + AWS)

This project provides a simple CloudOps assistant that connects to AWS services (EC2, S3) using `boto3` and allows natural language operations via LangGraph agents.

## Features

- 🔍 List EC2 instances
- 🚀 Restart EC2 instances
- 📦 List S3 buckets

## Setup

1. **Install dependencies**
```bash
pip install -r requirements.txt
```

2. **Configure AWS credentials**

Create a `.env` file:
```
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=ap-south-1
GOOGLE_API_KEY=key
```

3. **Run the Agent**
```bash
python main.py
```

Ask questions like:
- "List EC2 instances"
- "Restart i-0abc1234"
- "List all S3 buckets"

## License

MIT
