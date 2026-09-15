"""Revoke/uninstall only the signed package created by this desktop QA run."""

import argparse
import asyncio
import json
import secrets
from pathlib import Path

import httpx

from src.application.services.auth_service_v2 import AuthService
from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    BootstrapLocalPlatformAdministrator,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, engine
from src.infrastructure.adapters.secondary.persistence.sql_local_platform_administrator_repository import (
    SqlLocalPlatformAdministratorRepository,
)


async def run(apply: bool) -> None:  # noqa: PLR0915 - keep one-shot cleanup scope explicit
    directory = Path(__file__).resolve().parent
    fixture = json.loads((directory / "marketplace-wasm-fixture/install-request.json").read_text())
    if fixture["plugin_id"] != "qa-marketplace-marker-bundle":
        raise ValueError("Unexpected QA fixture")
    report = {"plugin_id": fixture["plugin_id"], "applied": False, "steps": []}
    if not apply:
        print(json.dumps(report))
        return
    settings = get_settings()
    async with async_session_factory() as session:
        bootstrap = BootstrapLocalPlatformAdministrator(
            repository=SqlLocalPlatformAdministratorRepository(session),
            hash_password=AuthService.get_password_hash,
            environment=settings.environment,
            database_host=settings.postgres_host,
            api_host="localhost",
        )
        password = secrets.token_urlsafe(48)
        identity = await bootstrap.execute(
            email=f"desktop-fixture-governance-{secrets.token_hex(8)}@localhost.invalid",
            password=password,
        )
        report["actor_id"] = identity.user_id
        report["temporary_identity_deactivated"] = False
        try:
            await session.commit()
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=120) as client:
                login = await client.post(
                    "/api/v1/auth/token", data={"username": identity.email, "password": password}
                )
                login.raise_for_status()
                client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
                package_url = f"/api/v1/plugin-marketplace/packages/{fixture['plugin_id']}"
                detail = await client.get(package_url, params={"include_revoked": "true"})
                detail.raise_for_status()
                versions = detail.json()["versions"]
                exact = [v for v in versions if v["version"] == fixture["version"]]
                if len(exact) != 1 or any(
                    exact[0][key] != expected
                    for key, expected in {
                        "publisher": fixture["publisher"],
                        "artifact_digest": fixture["artifact_sha256"],
                        "artifact_registry": fixture["artifact"]["registry"],
                        "artifact_repository": fixture["artifact"]["repository"],
                        "oci_manifest_digest": fixture["artifact"]["manifest_sha256"],
                        "manifest": fixture["manifest"],
                    }.items()
                ):
                    raise ValueError("Installed artifact does not match this task's signed fixture")
                for action, payload in (
                    (
                        "revoke",
                        {
                            "version": fixture["version"],
                            "reason": "Desktop QA lifecycle acceptance completed",
                        },
                    ),
                    (
                        "uninstall",
                        {"version": fixture["version"], "tenant_id": fixture["tenant_id"]},
                    ),
                ):
                    result = await client.post(f"{package_url}/{action}", json=payload)
                    report["steps"].append({"action": action, "status_code": result.status_code})
                    result.raise_for_status()
                    report["steps"][-1]["result"] = result.json()
                after = await client.get(package_url, params={"include_revoked": "true"})
                after.raise_for_status()
                target = next(
                    v for v in after.json()["versions"] if v["version"] == fixture["version"]
                )
                report["after"] = {
                    key: target[key]
                    for key in ("plugin_id", "version", "install_status", "revoked")
                }
                if not target["revoked"] or target["install_status"] != "uninstalled":
                    raise ValueError("Fixture governance did not reach the expected terminal state")
                report["applied"] = True
        finally:
            try:
                try:
                    await session.rollback()
                except Exception as rollback_error:
                    report["rollback_error_type"] = type(rollback_error).__name__
                # A fresh session handles an ambiguous initial commit acknowledgement.
                async with async_session_factory() as cleanup_session:
                    cleanup = BootstrapLocalPlatformAdministrator(
                        repository=SqlLocalPlatformAdministratorRepository(cleanup_session),
                        hash_password=AuthService.get_password_hash,
                        environment=settings.environment,
                        database_host=settings.postgres_host,
                        api_host="localhost",
                    )
                    await cleanup.deactivate(identity)
                    await cleanup_session.commit()
                report["temporary_identity_deactivated"] = True
            except Exception as cleanup_error:
                report["cleanup_error_type"] = type(cleanup_error).__name__
                raise
            finally:
                (directory / "cloud-fixture-governance-result.json").write_text(
                    json.dumps(report, indent=2) + "\n"
                )
    print(json.dumps(report))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    try:
        await run(parser.parse_args().apply)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        raise SystemExit(f"Fixture governance failed ({type(error).__name__})") from None
