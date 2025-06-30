import requests
from auth.gcp_auth import get_gcp_access_token
from credentials.gcp_secret import load_aws_credentials_from_gcp
from auth.aws_signer import sign_aws_request


def request_executor_agent(state: dict) -> dict:
    print(f"Executing request with state: {state}")

    url = state.get("endpoint")
    method = state.get("http_method", "GET").upper()
    body = state.get("request_parameters", "")
    headers = state.get("headers", {}).copy()
    auth_type = state.get("auth_type", "none")
    region = state.get("region")
    service = state.get("service")

    if not url:
        return {**state, "error": "Missing 'endpoint' in state", "response": None}

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
            print(f"post URL: {url}")
            resp = requests.post(url, headers=headers, data=body)
        else:
            full_url = f"{url}?{body}" if body else url
            print(f"GET URL: {full_url}")
            resp = requests.get(full_url, headers=headers)

        try:
            return {**state, "response": resp.json()}
        except Exception:
            return {**state, "response": resp.text}

    except Exception as e:
        print(f"Exception during request execution: {e}")
        return {
            **state,
            "error": str(e),
            "response": None
        }
