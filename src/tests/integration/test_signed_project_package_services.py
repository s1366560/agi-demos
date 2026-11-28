"""Exercise project capability linkage with separately signed Billing OCI/Wasm releases."""

import asyncio
import base64
import hashlib
import json
import os
from dataclasses import dataclass

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from plugins.business.billing.build import PLAN_PLUGIN, PLAN_SERVICE, PLUGIN, ROOT, build_release
from src.configuration.config import get_settings
from src.host.operations.project_package_readiness import (
    ProjectPackageReplicaReadiness,
)
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2 import project_package_execution
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.integration.test_signed_invoice_worker import db_session as _db
from src.tests.unit.routers.test_optional_business_http_v2 import (
    http as _http,
    publisher as _publisher,
)

db_session = _db
http = _http
publisher = _publisher
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        os.getenv("OCI_WORKER_DOCKER_TESTS") != "1"
        or os.getenv("INVOICE_WORKER_POSTGRES_TESTS") != "1",
        reason="requires Docker and disposable PostgreSQL QA schema",
    ),
]
SCOPE = {"tenant_id": "t", "project_id": "p"}
OTHER = {"tenant_id": "sibling", "project_id": "q"}
BASE = "/api/v1/platform-plugins/v2/optional-business"


@pytest.fixture(scope="module")
def releases():
    consumers, providers = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keys = tuple(
        k.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
        for k in (consumers, providers)
    )
    plans = json.loads((ROOT / "plans.json").read_bytes())
    with disposable_worker_registry() as (publish, url, engine):
        image = publish(ROOT)
        worker = build_release(
            plans, version="3.0.0", signer=consumers, worker_image=image, plan_service=True
        )
        previous = build_release(plans, version="1.0.0", signer=providers, plan_service=True)
        updated = build_release(
            {**plans, "pro": 987654}, version="1.1.0", signer=providers, plan_service=True
        )
        # A publisher can independently change the service ABI in their package source.
        with pytest.MonkeyPatch.context() as version_change:
            from plugins.business.billing import build as billing_builder

            version_change.setattr(
                billing_builder, "PLAN_SERVICE", {**PLAN_SERVICE, "version": "2.0.0"}
            )
            incompatible = build_release(
                plans, version="2.0.0", signer=providers, plan_service=True
            )
        yield keys, worker, previous, updated, url, engine, incompatible


@dataclass
class ProjectApi:
    client: object
    headers: dict
    sessions: object
    keys: tuple

    async def post(self, path, payload, status=200, scope=SCOPE):
        r = await self.client.post(BASE + path, json={**scope, **payload}, headers=self.headers)
        assert r.status_code == status, (r.status_code, r.text)
        return r.json()

    async def install(self, raw, scope=SCOPE):
        body = {"archive_base64": base64.b64encode(raw).decode()}
        probe = await self.post("/inspect", body, scope=scope)
        await self.post(
            "/install", {**body, "approved_permissions": probe["permissions"]}, scope=scope
        )
        return probe

    async def action(self, plugin, name, status=200, scope=SCOPE):
        return await self.post("/" + plugin + "/" + name, {}, status, scope)

    async def quote(self, status=200, scope=SCOPE):
        return await self.post(
            "/" + PLUGIN + "/invoke",
            {"tool_name": "quote", "payload": {"plan": "pro"}},
            status,
            scope,
        )

    async def ready(self, probe):
        async with self.sessions() as db:
            return await probe.ready(db, self.keys)

    async def controlled_quote(self, progress):
        async with self.sessions() as db:
            scope = ScopeBindingV2(**SCOPE)
            service = ProjectPluginInstallationService(db, scope, self.keys)
            return await service.call_active(
                PLUGIN,
                lambda package: project_package_execution.invoke_project_tool(
                    package, scope, "quote", {"plan": "pro"}, progress
                ),
            )


@pytest.fixture
async def project(http, db_session, releases, monkeypatch):
    assert await db_session.scalar(text("SELECT current_database()")) == "memstack_qa_sync_20260907"
    assert (await db_session.scalar(text("SELECT current_schema()"))).startswith("invoice_worker_")
    keys, _, _, _, url, _, _ = releases
    client, users = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = keys
    settings = get_settings().model_copy(update={"plugin_worker_allowed_registries": (url,)})
    monkeypatch.setattr(project_package_execution, "get_settings", lambda: settings)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def database():
        async with sessions() as session:
            yield session

    client._transport.app.dependency_overrides[get_db] = database
    db_session.add(Tenant(id="sibling", name="Sibling", slug="sibling", owner_id="owner"))
    await db_session.flush()
    db_session.add(Project(id="q", tenant_id="sibling", name="Other project", owner_id="owner"))
    await db_session.flush()
    db_session.add_all(
        [
            UserTenant(id="sibling-ut", tenant_id="sibling", user_id="owner", role="owner"),
            UserProject(id="sibling-up", project_id="q", user_id="owner", role="owner"),
        ]
    )
    await db_session.commit()
    return ProjectApi(client, {"Authorization": f"Bearer {users['owner']}"}, sessions, keys)


async def test_independent_provider_upgrade_rollback_withdraw_and_scope(project, releases):
    _, worker, previous, updated, _, _, incompatible = releases
    await project.post(
        "/install",
        {
            "archive_base64": base64.b64encode(previous).decode(),
            "approved_permissions": ["tools.execute"],
        },
        400,
    )
    await project.install(previous, OTHER)
    await project.action(PLAN_PLUGIN, "enable", scope=OTHER)
    consumer = await project.install(worker)
    assert consumer["requires"] == [{"alias": "plans", **PLAN_SERVICE}]
    await project.action(PLUGIN, "enable", 409)
    provider = await project.install(previous)
    assert provider["provides"] == [PLAN_SERVICE]
    await project.action(PLAN_PLUGIN, "enable")
    await project.action(PLUGIN, "enable")
    readiness = ProjectPackageReplicaReadiness()
    assert await project.ready(readiness)
    first = await project.quote()
    assert first["storage_limit"] == json.loads((ROOT / "plans.json").read_bytes())["pro"]

    async def upgrade(_event):
        await project.install(updated)
        await project.action(PLAN_PLUGIN, "enable")

    assert await project.controlled_quote(upgrade) == first
    assert (await project.quote())["storage_limit"] == 987654
    await project.action(PLAN_PLUGIN, "rollback")
    assert await project.quote() == first
    assert await project.ready(readiness)

    async def withdraw_and_reenable(_event):
        await project.action(PLAN_PLUGIN, "disable")
        assert not await project.ready(readiness)
        await project.action(PLAN_PLUGIN, "enable")

    with pytest.raises(OptionalBusinessError, match="authorization has ended"):
        await project.controlled_quote(withdraw_and_reenable)
    assert await project.quote() == first
    assert await project.ready(readiness)
    await project.install(incompatible)
    await project.action(PLAN_PLUGIN, "enable", 409)
    assert await project.quote() == first
    await project.action(PLAN_PLUGIN, "disable")
    await project.quote(403)
    await project.quote(403, scope=OTHER)


async def test_cancelled_capability_consumer_stops_its_container(project, releases):
    _, worker, previous, _, _, engine, _ = releases
    await project.install(previous)
    await project.action(PLAN_PLUGIN, "enable")
    consumer = await project.install(worker)
    await project.action(PLUGIN, "enable")
    admitted = asyncio.Event()

    async def pause(_event):
        admitted.set()
        await asyncio.Future()

    task = asyncio.create_task(project.controlled_quote(pause))
    try:
        await asyncio.wait_for(admitted.wait(), timeout=15)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not engine.containers.list(
        all=True, filters={"label": "memstack.release=" + consumer["digest"]}
    )
    assert (await project.quote())["plan"] == "pro"


async def test_revoked_provider_digest_stops_admitted_call_and_other_project_lookup(
    project, releases
):
    _, worker, previous, updated, _, _, _ = releases
    initial = await project.install(previous)
    await project.action(PLAN_PLUGIN, "enable")
    await project.install(worker)
    await project.action(PLUGIN, "enable")

    async def withdraw_version(_event):
        # Apply the catalog administrator's committed withdrawal to this isolated QA schema.
        digest = hashlib.sha256(previous).hexdigest()
        async with project.sessions() as session, session.begin():
            session.add(
                PlatformPluginPackageModel(
                    plugin_id=PLAN_PLUGIN,
                    version="1.0.0",
                    publisher="plans",
                    artifact_digest=digest,
                    artifact_registry="registry.example.test",
                    artifact_repository="billing/plans",
                    oci_manifest_digest=digest,
                    manifest={"digest": initial["digest"]},
                    security_scan_status="passed",
                    revoked=True,
                )
            )

    with pytest.raises(OptionalBusinessError, match="revoked"):
        await project.controlled_quote(withdraw_version)
    assert "revoked" in (await project.quote(403))["detail"]
    assert not await project.ready(ProjectPackageReplicaReadiness())
    await project.install(updated)
    await project.action(PLAN_PLUGIN, "enable")
    assert (await project.quote())["storage_limit"] == 987654
