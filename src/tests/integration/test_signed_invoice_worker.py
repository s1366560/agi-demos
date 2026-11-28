"""Publish two real Billing guest images to an isolated registry and invoke the signed project APIs."""

import base64
import json
import os
import shutil
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.operations.ops import ModifyTableOps
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from plugins.business.billing.build import ROOT, build_release
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2 import project_package_execution
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.routers.test_optional_business_http_v2 import (
    http as _http,
    publisher as _publisher,
)

http = _http
publisher = _publisher

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


@pytest.fixture
async def db_session(test_db):
    if os.getenv("INVOICE_WORKER_POSTGRES_TESTS") != "1":
        yield test_db
        return
    qa = "memstack_qa_sync_20260907"
    schema = "invoice_worker_" + uuid4().hex
    url = sa.engine.make_url(get_settings().postgres_url).set(database=qa)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema, "lock_timeout": "5s"}}
    )

    def bootstrap(connection):
        metadata = sa.MetaData()
        for name in (
            "users",
            "tenants",
            "projects",
            "roles",
            "user_roles",
            "api_keys",
            "user_sessions",
            "user_tenants",
            "user_projects",
            "project_plugin_installations",
            "project_plugin_releases",
            "platform_plugin_packages",
            "platform_plugin_namespace_kv_v2",
        ):
            Base.metadata.tables[name].to_metadata(metadata)
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        for op in produce_migrations(context, metadata).upgrade_ops.ops:
            for individual in op.ops if isinstance(op, ModifyTableOps) else [op]:
                operations.invoke(individual)

    created = False
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(sa.text("SELECT current_database()")) == qa
            await connection.execute(CreateSchema(schema))
            assert await connection.scalar(sa.text("SELECT current_schema()")) == schema
            await connection.run_sync(bootstrap)
        created = True
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        if created:
            async with engine.begin() as connection:
                assert await connection.scalar(sa.text("SELECT current_database()")) == qa
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


@pytest.fixture(scope="module")
def invoice_releases(tmp_path_factory):
    folder = tmp_path_factory.mktemp("billing-independent-upgrade")
    (folder / "workers").mkdir()
    for name in (
        "workers/invoice_worker.py",
        "workers/invoice_contract.py",
        "invoice_record.py",
        "Dockerfile",
        ".dockerignore",
        "workers/invoice_terms.json",
        "plans.json",
    ):
        shutil.copyfile(ROOT / name, folder / name)
    worker = folder / "workers/invoice_worker.py"
    code = worker.read_text()
    # A genuine publisher code change, including a regression to exercise transactional recovery.
    assert "due = end + timedelta(days=TERMS_DAYS)" in code
    assert 'return {"invoice": invoice, "error": None}' in code
    worker.write_text(
        code.replace("days=TERMS_DAYS", "days=TERMS_DAYS + 1").replace(
            'return {"invoice": invoice, "error": None}',
            'return {} if invoice["currency"] == "XXX" else {"invoice": invoice, "error": None}',
        )
    )
    key = Ed25519PrivateKey.generate()
    with disposable_worker_registry() as (publish, registry, _):
        plans = json.loads((ROOT / "plans.json").read_bytes())
        releases = [
            base64.b64encode(
                build_release(plans, version=version, signer=key, worker_image=publish(context))
            ).decode()
            for version, context in (("2.0.0", ROOT), ("2.1.0", folder))
        ]
        public = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        yield public, releases, registry


@pytest.fixture
async def invoice_project(
    http,
    db_session,
    invoice_releases,
    monkeypatch,
):
    public, releases, registry = invoice_releases
    client, keys = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    settings = get_settings().model_copy(update={"plugin_worker_allowed_registries": (registry,)})
    monkeypatch.setattr(project_package_execution, "get_settings", lambda: settings)
    if db_session.get_bind().dialect.name == "postgresql":
        sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

        async def database():
            async with sessions() as session:
                yield session

        client._transport.app.dependency_overrides[get_db] = database
    scope = {"tenant_id": "t", "project_id": "p"}
    other = {"tenant_id": "invoice-tenant", "project_id": "invoice-project"}
    db_session.add(
        Tenant(id=other["tenant_id"], name="Other", slug="other-invoice", owner_id="owner")
    )
    await db_session.flush()
    db_session.add(
        Project(
            id=other["project_id"],
            tenant_id=other["tenant_id"],
            name="Other project",
            owner_id="owner",
        )
    )
    await db_session.flush()
    db_session.add(
        UserTenant(
            id="ut-other-invoice", user_id="owner", tenant_id=other["tenant_id"], role="owner"
        )
    )
    db_session.add(
        UserProject(
            id="up-other-invoice", user_id="owner", project_id=other["project_id"], role="owner"
        )
    )
    await db_session.commit()
    base = "/api/v1/platform-plugins/v2/optional-business"
    root = base + "/memstack-billing"
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    viewer = {"Authorization": f"Bearer {keys['viewer']}"}

    async def install(archive, binding):
        data = {**binding, "archive_base64": archive}
        probe = await client.post(base + "/inspect", json=data, headers=headers)
        assert probe.status_code == 200, probe.text
        assert set(probe.json()["permissions"]) == {
            "app.billing.account.read",
            "app.billing.plan.write",
            "storage.read",
            "storage.write",
            "tools.execute",
            "ui.slot",
        }
        recorded = await client.post(
            base + "/install",
            json={**data, "approved_permissions": probe.json()["permissions"]},
            headers=headers,
        )
        assert recorded.status_code == 200, recorded.text
        ready = await client.post(root + "/enable", json=binding, headers=headers)
        assert ready.status_code == 200, ready.text
        return probe.json()["digest"]

    async def invoke(tool, payload, *, binding=scope, auth=headers, status=200, digest=None):
        res = await client.post(
            root + "/invoke",
            json={**binding, "tool_name": tool, "payload": payload, "expected_digest": digest},
            headers=auth,
        )
        assert res.status_code == status, res.text
        return res.json()

    return install, invoke, releases, scope, other, viewer, client, root, headers


async def test_project_invoices_follow_signed_code_and_keep_committed_rows(invoice_project):
    install, invoke, releases, scope, other, viewer, client, root, headers = invoice_project
    baseline = await install(releases[0], scope)
    invoice = {
        "idempotency_key": "order-A",
        "currency": "USD",
        "amount": 950,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    await invoke("invoice.create", invoice, auth=viewer, status=403)
    first = (await invoke("invoice.create", invoice, digest=baseline))["invoice"]
    assert first["amount"] == 950 and first["status"] == "pending"
    assert (await invoke("invoice.create", invoice))["invoice"] == first
    assert (await invoke("invoice.create", {**invoice, "amount": 951}))[
        "error"
    ] == "idempotency_conflict"
    assert (await invoke("invoice.get", {"id": first["id"]}))["invoice"] == first
    assert (await invoke("invoice.list", {}))["invoices"] == [first]
    await install(releases[0], other)
    assert (await invoke("invoice.get", {"id": first["id"]}, binding=other))["error"] == "not_found"
    assert (await invoke("invoice.list", {}, binding=other))["invoices"] == []
    await invoke(
        "invoice.list", {}, binding={"tenant_id": other["tenant_id"], "project_id": "p"}, status=404
    )

    updated = await install(releases[1], scope)
    await invoke("invoice.list", {}, digest=baseline, status=409)
    second = (
        await invoke("invoice.create", {**invoice, "idempotency_key": "order-B"}, digest=updated)
    )["invoice"]
    assert datetime.fromisoformat(second["due_at"]) - datetime.fromisoformat(
        first["due_at"]
    ) == timedelta(days=1)
    failed = {**invoice, "idempotency_key": "broken-attempt", "currency": "XXX"}
    await invoke("invoice.create", failed, status=400)
    rollback = await client.post(root + "/rollback", json=scope, headers=headers)
    assert rollback.status_code == 200, rollback.text
    assert (await invoke("invoice.get", {"id": second["id"]}, digest=baseline))["invoice"] == second
    assert (await invoke("invoice.create", {**invoice, "idempotency_key": "order-B"}))[
        "invoice"
    ] == second
    second_page = await invoke("invoice.list", {"limit": 1})
    next_page = await invoke("invoice.list", {"after": second_page["next_cursor"], "limit": 1})
    assert next_page["next_cursor"] is None
    assert {r["id"] for r in second_page["invoices"] + next_page["invoices"]} == {
        first["id"],
        second["id"],
    }
    recovered = await invoke("invoice.create", {**failed, "currency": "EUR"})
    assert recovered["invoice"]["due_at"] == first["due_at"]
    commanded = await client.post(
        root + "/commands", json={**scope, "command_id": "list-invoices"}, headers=headers
    )
    assert len(commanded.json()["invoices"]) == 3
