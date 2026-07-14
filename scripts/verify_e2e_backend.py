"""Verify that the backend E2E fixture completed auth and tenant bootstrap."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol, cast

import httpx


class _Response(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _Client(Protocol):
    def post(self, url: str, *, data: Mapping[str, str]) -> _Response: ...

    def get(self, url: str, *, headers: Mapping[str, str]) -> _Response: ...


def _verify(api_base: str, client: _Client) -> None:
    auth_response = client.post(
        f"{api_base.rstrip('/')}/api/v1/auth/token",
        data={"username": "admin@memstack.ai", "password": "adminpassword"},
    )
    auth_response.raise_for_status()
    auth_payload = auth_response.json()
    token = auth_payload.get("access_token") if isinstance(auth_payload, Mapping) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("backend bootstrap did not return an access token")

    tenant_response = client.get(
        f"{api_base.rstrip('/')}/api/v1/tenants/",
        headers={"Authorization": f"Bearer {token}"},
    )
    tenant_response.raise_for_status()
    tenant_payload = tenant_response.json()
    tenants = (
        tenant_payload.get("tenants") if isinstance(tenant_payload, Mapping) else tenant_payload
    )
    if not isinstance(tenants, list) or not tenants:
        raise RuntimeError("backend bootstrap did not create a tenant")


def verify_backend(api_base: str, *, client: _Client | None = None) -> None:
    """Fail unless the E2E backend can authenticate and list a bootstrapped tenant."""
    if client is not None:
        _verify(api_base, client)
        return

    with httpx.Client(timeout=10.0) as http_client:
        _verify(api_base, cast("_Client", http_client))


if __name__ == "__main__":
    verify_backend(os.getenv("API_BASE", "http://localhost:8000"))
    print("Backend E2E bootstrap verified")
