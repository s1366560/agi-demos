"""Install a signed dashboard into an isolated tenant and exercise the canonical run registry."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Request

from plugins.business.agent.backend.dashboard_operations import DASHBOARD_PERMISSIONS
from plugins.business.agent.release import build_release
from src.host.operations.tenant_commands import TenantPackageContext, tenant_command
from src.host.packages.tenant_installation import TenantPackageService
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Tenant, User
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.bundle_archive import declared_bundle_permissions_v2
from src.infrastructure.plugins.v2.project_package_execution import dispatch_project_command
from src.infrastructure.plugins.v2.project_plugin_package import admit_package
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)
from src.tests.unit.routers.test_optional_business_http_v2 import (
    http as _http,
    publisher as _publisher,
)

http = _http
publisher = _publisher

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def test_installed_dashboard_enforces_tenant_and_conversation_access(  # noqa: PLR0915
    http, db_session, monkeypatch
):
    assert str(db_session.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    client, _actors = http
    app = client._transport.app
    app.state.tenant_package_operations_v1 = {}
    signer = Ed25519PrivateKey.generate()
    key = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    release = build_release("example.test/worker@sha256:" + "a" * 64, "1.6.0", signer)
    service = TenantPackageService(db_session, "t", (key,), "owner")
    project_scope = ScopeBindingV2(tenant_id="t", project_id="p")
    old_grants = declared_bundle_permissions_v2(release) - DASHBOARD_PERMISSIONS
    inspected = admit_package(
        release, (key,), declared_bundle_permissions_v2(release), project_scope
    )
    assert inspected.approved_permissions == old_grants
    project = admit_package(release, (key,), old_grants, project_scope)
    assert all(page.scope == "project" for page in project.contribution.pages)
    assert any(page.device_tools for page in project.contribution.pages)
    with pytest.raises(OptionalBusinessError) as denied:
        await dispatch_project_command(project, project_scope, "dashboard-read", {"view": "runs"})
    assert denied.value.code == "forbidden"
    reviewed = await service.inspect(release)
    assert DASHBOARD_PERMISSIONS | {"ui.slot", "tools.execute"} <= reviewed.approved_permissions
    await service.record(
        release, reviewed.approved_permissions, 0, reviewed.digest, identity=None, activate=True
    )
    package = await service.active("memstack-agent", reviewed.digest)
    ctx = TenantPackageContext(
        Request({"type": "http", "app": app, "method": "POST", "path": "/command", "headers": []}),
        db_session,
        await db_session.get(User, "viewer"),
        service.scope,
    )

    async def call(command, payload):
        return await tenant_command(ctx, package, command, payload)

    db_session.add(Tenant(id="foreign", name="Foreign", slug="foreign", owner_id="owner"))
    await db_session.flush()
    for conversation, tenant, user in [
        ("mine", "t", "viewer"),
        ("other", "t", "owner"),
        ("outside", "foreign", "viewer"),
    ]:
        db_session.add(
            Conversation(
                id=conversation, tenant_id=tenant, project_id="p", user_id=user, title=conversation
            )
        )
    await db_session.flush()
    registry = SubAgentRunRegistry()
    from src.infrastructure.adapters.primary.web.routers.agent import trace_router

    monkeypatch.setattr(trace_router, "current_subagent_run_registry_v2", lambda: registry)
    for conversation in ("mine", "other", "outside"):
        run = registry.create_run(conversation, "parent", "task", metadata={"source": "private"})
        registry.set_trace_context(conversation, run.run_id, "trace")
        child = registry.create_run(conversation, "child", "child task")
        registry.set_trace_context(conversation, child.run_id, "trace", parent_span_id=run.run_id)
    runs = await call("dashboard-read", {"view": "runs"})
    assert len(runs["runs"]) == 2
    assert {run["conversation_id"] for run in runs["runs"]} == {"mine"}
    assert all(run["metadata"] == {} for run in runs["runs"])
    assert (await call("dashboard-read", {"view": "active"}))["active_count"] == 2
    assert await call("dashboard-read", {"view": "permission"}) == {"can_modify": False}
    chain = await call("dashboard-trace", {"conversation_id": "mine", "trace_id": "trace"})
    assert chain["total"] == 2
    assert chain["runs"][1]["parent_span_id"] == chain["runs"][0]["run_id"]
    assert chain["runs"][0]["metadata"]["source"] == "private"
    for conversation in ("other", "outside"):
        with pytest.raises(OptionalBusinessError) as denied:
            await call("dashboard-trace", {"conversation_id": conversation, "trace_id": "trace"})
        assert denied.value.code == "page_not_found"
    with pytest.raises(OptionalBusinessError) as denied:
        await call("chat-list", {})
    assert denied.value.code == "forbidden"


def test_signed_page_rejects_command_from_another_scope():
    import json
    from pathlib import Path

    from memstack_plugin_sdk.contract import ContractError, parse_contribution

    manifest = Path(__file__).resolve().parents[3] / "plugins/business/agent/contributions.json"
    contribution = json.loads(manifest.read_bytes())
    command = next(item for item in contribution["commands"] if item["id"] == "dashboard-read")
    command["scope"] = "project"
    with pytest.raises(ContractError, match="command unavailable in page installation scope"):
        parse_contribution(contribution)
    command["scope"] = "unknown"
    with pytest.raises(ContractError, match="unknown command installation scope"):
        parse_contribution(contribution)
