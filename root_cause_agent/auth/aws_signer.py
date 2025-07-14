import datetime, hashlib, hmac
from urllib.parse import urlparse

def sign_aws_request(method, url, region, service, body, access_key, secret_key):
    t = datetime.datetime.utcnow()
    amz_date = t.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = t.strftime('%Y%m%d')
    parsed_url = urlparse(url)
    host = parsed_url.netloc
    canonical_uri = parsed_url.path or "/"
    canonical_querystring = "" if method == "POST" else body
    content_type = "application/x-www-form-urlencoded; charset=utf-8"

    canonical_headers = f"content-type:{content_type}\\nhost:{host}\\nx-amz-date:{amz_date}\\n"
    signed_headers = "content-type;host;x-amz-date"
    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    canonical_request = "\\n".join([
        method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, payload_hash
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\\n".join([
        algorithm, amz_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    ])

    def sign(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    kDate = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    kRegion = sign(kDate, region)
    kService = sign(kRegion, service)
    kSigning = sign(kService, "aws4_request")
    signature = hmac.new(kSigning, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "x-amz-date": amz_date,
        "Content-Type": content_type
    }
