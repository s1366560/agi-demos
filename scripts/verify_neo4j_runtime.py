"""Verify the authenticated graph capability during Neo4j stop/restart tests."""

from __future__ import annotations

import argparse
import os
import time
from typing import cast

import httpx

from scripts.verify_e2e_graph import _require_mapping, _require_string, verify_backend_capability


def verify_neo4j_runtime(api_base: str, *, expect_available: bool) -> None:
    """Poll until the API exposes the expected structured graph runtime state."""
    base = api_base.rstrip("/")
    deadline = time.monotonic() + 60.0
    last_error: Exception | None = None
    with httpx.Client(timeout=15.0) as client:
        auth = client.post(
            f"{base}/api/v1/auth/token",
            data={"username": "admin@memstack.ai", "password": "adminpassword"},
        )
        _ = auth.raise_for_status()
        token = _require_string(
            _require_mapping(cast("object", auth.json()), "an authentication object"),
            "access_token",
            "an access token",
        )
        headers = {"Authorization": f"Bearer {token}"}

        anonymous = client.get(f"{base}/api/v1/search-enhanced/capabilities")
        if anonymous.status_code != 401:
            raise RuntimeError("Neo4j runtime capability did not reject anonymous access")

        while time.monotonic() < deadline:
            try:
                response = client.get(
                    f"{base}/api/v1/search-enhanced/capabilities",
                    headers=headers,
                )
                _ = response.raise_for_status()
                verify_backend_capability(
                    cast("object", response.json()),
                    available=expect_available,
                )
                return
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                time.sleep(1.0)

    state = "available" if expect_available else "degraded"
    raise RuntimeError(f"Neo4j runtime did not reach {state}: {type(last_error).__name__}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=("available", "degraded"), required=True)
    args = parser.parse_args()
    verify_neo4j_runtime(
        os.getenv("API_BASE", "http://127.0.0.1:8000"),
        expect_available=args.expect == "available",
    )
    print(f"Neo4j runtime capability verified: {args.expect}")
