from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.cloud import secretmanager
import json
import os
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.expanduser("~/.gcp/keys/gcp-sa-key.json")

def get_service_account_from_secret(secret_name="gcp-sa-key", project_id="spiritual-verve-461804-h5"):
    try:
        print(f"Connecting to GCP Secret Manager in project: {project_id}")
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return json.loads(response.payload.data.decode("UTF-8"))
    except Exception as e:
        print(f"Failed to access secret: {e}")
        raise RuntimeError(f"GCP Secret Manager access failed: {e}")


def get_gcp_access_token(scopes=None, secret_name="gcp-sa-key", project_id="spiritual-verve-461804-h5"):
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    try:
        sa_info = get_service_account_from_secret(secret_name, project_id)
        credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)
        print(credentials.service_account_email)
        credentials.refresh(Request())
        return credentials.token
    except Exception as e:
        raise RuntimeError(f"GCP OAuth token generation failed: {e}")
