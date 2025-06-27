from google.cloud import secretmanager
import json
import os

def load_aws_credentials_from_gcp(secret_name="aws-credentials", project_id="spiritual-verve-461804-h5"):
    if not project_id:
        project_id = os.environ.get("GCP_PROJECT_ID")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("UTF-8"))
