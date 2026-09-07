#!/usr/bin/env python3
# ruff: noqa: N999
"""Provision 24-hour desktop data-plane grants through the normal local HTTP API.

Creates a separate temporary platform identity through the development-only
application bootstrap. It never elevates an existing account. The identity is
retired after issuance. Secrets are written only to an exclusive mode-0600 file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from src.application.services.auth_service_v2 import AuthService
from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    BootstrapLocalPlatformAdministrator,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import (
    async_session_factory,
    engine,
)
from src.infrastructure.adapters.secondary.persistence.sql_local_platform_administrator_repository import (
    SqlLocalPlatformAdministratorRepository,
)

_PLANES = ("desktop-sidecar-v2", "desktop-renderer-v2")


def _private_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def _require_success(response: httpx.Response, operation: str) -> None:
    if not response.is_success:
        raise RuntimeError(f"{operation} failed with HTTP {response.status_code}")


async def provision(api_base: str, output: Path, metadata_output: Path) -> None:
    settings = get_settings()
    parsed = urlsplit(api_base)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Provide a loopback API origin without credentials or path")
    if output.exists() or metadata_output.exists():
        raise ValueError("Bootstrap output paths must not already exist")
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    issued: list[dict[str, object]] = []
    async with async_session_factory() as session:
        use_case = BootstrapLocalPlatformAdministrator(
            repository=SqlLocalPlatformAdministratorRepository(session),
            hash_password=AuthService.get_password_hash,
            environment=settings.environment,
            database_host=settings.postgres_host,
            api_host=parsed.hostname or "",
        )
        password = secrets.token_urlsafe(48)
        identity = await use_case.execute(
            email=f"desktop-bootstrap-{secrets.token_hex(8)}@localhost.invalid",
            password=password,
        )
        await session.commit()
        try:
            async with httpx.AsyncClient(
                base_url=api_base.rstrip("/"), timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                login = await client.post(
                    "/api/v1/auth/token", data={"username": identity.email, "password": password}
                )
                _require_success(login, "Bootstrap login")
                client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
                try:
                    for plane in _PLANES:
                        response = await client.post(
                            "/api/v1/platform-plugins/v2/data-plane-credentials",
                            json={"data_plane_id": plane, "expires_at": expires_at.isoformat()},
                        )
                        _require_success(response, "Data-plane credential issuance")
                        record = response.json()
                        issued.append(record)
                        probe = await client.get(
                            "/api/v1/platform-plugins/v2/distribution",
                            headers={"Authorization": f"Bearer {record['secret']}"},
                        )
                        _require_success(probe, "Data-plane distribution authorization")
                    lines: list[str] = []
                    for record in issued:
                        prefix = (
                            "AGISTACK_PLUGIN_RENDERER_DATA_PLANE"
                            if record["data_plane_id"] == "desktop-renderer-v2"
                            else "AGISTACK_PLUGIN_DATA_PLANE"
                        )
                        lines.extend(
                            [
                                f"export {prefix}_CREDENTIAL_V2={shlex.quote(str(record['secret']))}",
                                f"export {prefix}_API_BASE_URL_V2={shlex.quote(api_base.rstrip('/'))}",
                                f"export {prefix}_ACK_PARTICIPATION_V2=true",
                            ]
                        )
                    metadata = {
                        "bootstrap_user_id": identity.user_id,
                        "bootstrap_id": identity.bootstrap_id,
                        "bootstrap_identity_retired_after_issuance": True,
                        "expires_at": expires_at.isoformat(),
                        "grants": [
                            {key: value for key, value in record.items() if key != "secret"}
                            for record in issued
                        ],
                    }
                    _private_file(metadata_output, json.dumps(metadata, indent=2) + "\n")
                    _private_file(output, "\n".join(lines) + "\n")
                except BaseException:
                    revocation_failures = 0
                    for record in issued:
                        try:
                            response = await client.delete(
                                "/api/v1/platform-plugins/v2/data-plane-credentials/"
                                + str(record["credential_id"])
                            )
                            _require_success(response, "Partial bootstrap credential revocation")
                        except Exception:
                            revocation_failures += 1
                    if revocation_failures:
                        raise RuntimeError(
                            "Partial bootstrap credential cleanup incomplete"
                        ) from None
                    raise
        finally:
            await session.rollback()
            await use_case.deactivate(identity)
            await session.commit()
    print(
        json.dumps(
            {
                "environment_file": str(output),
                "metadata_file": str(metadata_output),
                "data_planes": list(_PLANES),
                "expires_at": expires_at.isoformat(),
            }
        )
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    args = parser.parse_args()
    try:
        await provision(args.api_base, args.output.resolve(), args.metadata_output.resolve())
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Never print exception payloads from HTTP/SQL transports or secret-bearing objects.
        raise SystemExit(f"Local desktop grant bootstrap failed ({type(error).__name__})") from None
