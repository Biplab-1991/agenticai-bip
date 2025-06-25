FROM python:3.10-slim

WORKDIR /app
ENV PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server.py .

CMD ["python", "mcp_server.py"]
