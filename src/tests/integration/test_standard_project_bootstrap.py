"""Bootstrap the chart selection on empty PostgreSQL and independently upgrade a live package."""

import asyncio
import base64
import json
import os
import secrets
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from plugins.business.billing.build import build_release
from src.configuration.config import get_settings
from src.host.packages.bootstrap import bootstrap_empty_project
from src.host.transport.package_kernel import create_app
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    initialize_package_kernel_database,
)
from src.tests.integration.test_official_package_selection import deployment  # noqa: F401
from src.tests.integration.test_package_kernel_database import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PACKAGE_KERNEL_DATABASE_TESTS") != "1"
        or os.getenv("OCI_WORKER_DOCKER_TESTS") != "1",
        reason="needs a disposable PostgreSQL server and worker registry",
    ),
]


def _stage(root, archives, owner):
    (root / "owner.json").write_text(json.dumps(owner))
    shutil.copyfile(ROOT / "charts/memstack/files/standard-packages.json", root / "selection.json")
    files = root / "archives"
    files.mkdir()
    for raw in archives:
        with ZipFile(BytesIO(raw)) as archive:
            name = json.loads(archive.read("bundle.json"))["bundle_id"]
        (files / f"{name}.mspkg").write_bytes(raw)


async def _check_updates(client, scope, signer, restart):
    base = "/api/v1/platform-plugins/v2/optional-business"

    async def post(path, **body):
        result = await client.post(base + path, json={**scope, **body})
        result.raise_for_status()
        return result.json()

    async def versions():
        result = await client.get(base + "/", params=scope)
        result.raise_for_status()
        return {p["plugin_id"]: p["actual_digest"] for p in result.json()["items"]}

    async def quote():
        return (await post("/memstack-billing/invoke", tool_name="quote", payload={"plan": "pro"}))[
            "storage_limit"
        ]

    initial = await versions()
    assert len(initial) == 6 and all(initial.values())
    old_limit = await quote()
    catalog = json.loads((ROOT / "plugins/business/billing/plans.json").read_text())
    catalog["pro"] = old_limit + 1024
    raw = build_release(catalog, version="12.0.0", signer=signer)
    encoded = base64.b64encode(raw).decode()
    verified = await post("/inspect", archive_base64=encoded)
    await post("/install", archive_base64=encoded, approved_permissions=verified["permissions"])
    await post("/memstack-billing/enable")
    assert await quote() == old_limit + 1024
    await restart()
    assert await versions() == {**initial, "memstack-billing": verified["digest"]}
    health = await post(
        "/memstack-environments/invoke",
        tool_name="cluster_health",
        payload={"total_nodes": 2, "used_cpu": 1, "total_cpu": 4},
    )
    assert health["cpu_usage"] == 25
    await post("/memstack-billing/rollback")
    assert await quote() == old_limit and await versions() == initial


async def test_bootstrap_is_atomic_and_independent_updates_survive_restart(
    database,  # noqa: F811
    deployment,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    registry, public, archives = deployment
    signer = Ed25519PrivateKey.generate()
    keys = (
        public,
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    owner = {
        "email": "initial-owner@example.org",
        "password": secrets.token_urlsafe(30),
        "tenant_name": "Example",
        "project_name": "Standard",
    }
    _stage(tmp_path, archives, owner)
    await initialize_package_kernel_database(database)

    async def restart():
        await bootstrap_empty_project(database, tmp_path, keys)

    last = tmp_path / "archives/memstack-billing.mspkg"
    original = last.read_bytes()
    last.unlink()
    with pytest.raises(FileNotFoundError):
        await restart()
    async with database.connect() as connection:
        assert await connection.scalar(text("select count(*) from users")) == 0
        assert await connection.scalar(text("select count(*) from project_plugin_releases")) == 0
    last.write_bytes(original)
    await asyncio.gather(restart(), restart())
    app = create_app()
    app.state.plugin_marketplace_trusted_public_keys_v2 = keys
    sessions = async_sessionmaker(database, expire_on_commit=False)

    async def isolated_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = isolated_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        response = await client.get("/api/v1/project-packages/projects/")
        response.raise_for_status()
        (project,) = response.json()
        await _check_updates(
            client, {k: project[k] for k in ("tenant_id", "project_id")}, signer, restart
        )
