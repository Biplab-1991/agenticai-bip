from langchain_core.runnables import Runnable
from auth.gcp_auth import get_gcp_access_token
from credentials.gcp_secret import load_aws_credentials_from_gcp
from auth.aws_signer import sign_aws_request
import requests

class CloudOpsExecutor(Runnable):
    def invoke(self, state: dict) -> dict:
        print(f"Executing request with state: {state}")

        plan = state.get("plan", {})
        url = plan.get("endpoint")
        method = plan.get("http_method", "GET").upper()
        body = plan.get("request_parameters", "")
        headers = plan.get("headers", {}).copy() if plan.get("headers") else {}
        auth_type = plan.get("auth_type", "none")
        region = plan.get("region")
        service = plan.get("service")

        if not url:
            return {**state, "execution_result": {
                "status": "error",
                "error": "Missing 'endpoint' in plan",
                "output": None
            }}

        try:
            if auth_type == "oauth2":
                token = get_gcp_access_token(project_id="spiritual-verve-461804-h5")
                headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "sigv4":
                creds = load_aws_credentials_from_gcp()
                signed = sign_aws_request(
                    method=method,
                    url=url,
                    region=region,
                    service=service,
                    body=body,
                    access_key=creds["aws_access_key_id"],
                    secret_key=creds["aws_secret_access_key"]
                )
                headers.update(signed)

            if method == "POST":
                print(f"POST URL: {url}")
                resp = requests.post(url, headers=headers, data=body)
            else:
                full_url = f"{url}?{body}" if body else url
                print(f"GET URL: {full_url}")
                resp = requests.get(full_url, headers=headers)

            try:
                output = resp.json()
            except Exception:
                output = resp.text

            status = "success" if resp.ok else "error"
            return {**state, "execution_result": {
                "status": status,
                "output": output,
                "error": None if resp.ok else f"HTTP {resp.status_code}"
            }}

        except Exception as e:
            print(f"Exception during request execution: {e}")
            return {
                **state,
                "execution_result": {
                    "status": "error",
                    "error": str(e),
                    "output": None
                }
            }
