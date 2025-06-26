import requests
from auth.aws_signer import sign_aws_request
from auth.gcp_auth import get_gcp_access_token
from credentials.gcp_secret import load_aws_credentials_from_gcp

def request_executor_agent(state: dict) -> dict:
    print(f"state:::::::::{state}")
    url = state["endpoint"]
    method = state["http_method"].upper()
    body = state.get("request_parameters", "")
    headers = state.get("headers", {}).copy()

    auth_type = state.get("auth_type", "none")

    if auth_type == "sigv4":
        creds = load_aws_credentials_from_gcp()
        signed = sign_aws_request(
            method=method,
            url=url,
            region=state["region"],
            service=state["service"],
            body=body,
            access_key=creds["aws_access_key_id"],
            secret_key=creds["aws_secret_access_key"]
        )
        headers.update(signed)

    elif auth_type == "oauth2":
        token = get_gcp_access_token("spiritual-verve-461804-h5")
        headers["Authorization"] = f"Bearer {token}"

    if method == "POST":
        resp = requests.post(url, headers=headers, data=body)
    else:
        full_url = f"{url}?{body}" if body else url
        print(f"full_url:::::::::----------------{url}")
        resp = requests.get(full_url, headers=headers)

    try:
        return {"response": resp.json()}
    except Exception:
        return {"response": resp.text}
