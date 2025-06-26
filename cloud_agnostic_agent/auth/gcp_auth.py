from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.cloud import secretmanager
import json
import os

def get_service_account_from_secret(secret_name="gcp-sa-key", project_id=None):
    project_id = "spiritual-verve-461804-h5"
    print(f"project id:::::::::::::: {project_id}")
    if not project_id:
        raise ValueError("GCP project ID is not provided and not set in environment variable 'GCP_PROJECT_ID'.")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("UTF-8"))

def get_gcp_access_token(scopes=None, secret_name="gcp-sa-key", project_id=None):
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    sa_info = get_service_account_from_secret(secret_name, "spiritual-verve-461804-h5")
    credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)
    credentials.refresh(Request())
    return credentials.token
