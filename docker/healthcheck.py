"""Container health probes; standard library only, no model initialization."""

import json
import os
import sys
from urllib.request import Request, urlopen


def get_json(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=4) as response:
        return json.load(response)


def check(service):
    if service == "streamlit":
        with urlopen("http://127.0.0.1:8501/_stcore/health", timeout=4) as response:
            if response.status != 200 or response.read().strip() != b"ok":
                raise RuntimeError("Streamlit is not healthy")
        return
    if service != "api":
        raise ValueError("Expected api or streamlit")
    if get_json("http://127.0.0.1:8000/health").get("ready") is not True:
        raise RuntimeError("API engine is not ready")
    url = os.environ["QDRANT_URL"].rstrip("/")
    key = os.getenv("QDRANT_API_KEY")
    headers = {"api-key": key} if key else {}
    collection = get_json(url + "/collections/supreme_court_2023", headers)
    if collection["result"]["points_count"] != 21451:
        raise RuntimeError("Qdrant must contain exactly 21,451 points")


if __name__ == "__main__":
    try:
        check(sys.argv[1])
    except Exception:
        # Do not expose credentials, request headers or URLs in health logs.
        print("Service readiness check failed", file=sys.stderr)
        sys.exit(1)
