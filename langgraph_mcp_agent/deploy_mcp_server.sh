#!/bin/bash

# === CONFIG ===
PROJECT_ID="spiritual-verve-461804-h5"             # CHANGE THIS
SERVICE_NAME="mcp-server"
REGION="us-central1"
PORT=8080

# === Get project number ===
echo "🔍 Getting project number for $PROJECT_ID..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

if [ -z "$PROJECT_NUMBER" ]; then
  echo "❌ Failed to retrieve project number. Check project ID."
  exit 1
fi

echo "📦 Project number: $PROJECT_NUMBER"

# === Grant permissions to Cloud Build service account ===
SA="$PROJECT_NUMBER@cloudbuild.gserviceaccount.com"
echo "🔐 Granting roles to $SA..."

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" \
  --role="roles/run.developer" \
  --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountUser" \
  --quiet

# === Deploy to Cloud Run ===
echo "🚀 Deploying $SERVICE_NAME to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --project "$PROJECT_ID" \
  --port "$PORT"

echo "✅ Deployment complete!"
