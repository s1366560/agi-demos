"""Set and restore an isolated workbench user's saved language for layout comparisons."""

import os
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx


@contextmanager
def workbench_language(owner, language):
    api = os.getenv("MEMSTACK_QA_NATIVE_API", "http://127.0.0.1:8000")
    assert urlsplit(api).hostname in {"localhost", "127.0.0.1", "::1"}
    with httpx.Client(base_url=api + "/api/v1", timeout=30) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        ).raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        before = client.get("/users/me").raise_for_status().json().get("preferred_language")
        # With no saved preference both clients already honor the browser locale.
        if not before or before == language:
            yield
            return

        def select(value):
            updated = client.put("/users/me", json={"preferred_language": value}).raise_for_status()
            assert updated.json()["preferred_language"] == value

        select(language)
        try:
            yield
        finally:
            select(before)
