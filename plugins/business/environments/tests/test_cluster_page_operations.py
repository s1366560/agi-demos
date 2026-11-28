from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from plugins.business.environments.backend import (
    cluster_operations as ops,
    cluster_runner_operations as runner_ops,
)
from plugins.business.environments.backend.inventory_operations import project_inventory_row
from src.application.schemas.cluster_schemas import ClusterResponse
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit


@pytest.fixture
def cluster(monkeypatch):
    ctx = SimpleNamespace(
        request=object(), user=object(), db=object(), scope=SimpleNamespace(tenant_id="t")
    )
    row = ClusterResponse(
        id="id",
        name="test",
        tenant_id="t",
        created_at=datetime.now(UTC),
        provider_config={"nodes": 2},
        credentials_encrypted="private",
    )
    auth = object()

    async def authority(request, user, tenant, db) -> AsyncIterator[object]:
        assert (request, user, tenant, db) == (ctx.request, ctx.user, "t", ctx.db)
        yield auth

    check = AsyncMock()
    monkeypatch.setattr(ops, "require_tenant_access", check)
    monkeypatch.setattr(ops, "cluster_application_authority_dependency_v2", authority)
    for name in ("create", "update", "get", "delete"):
        monkeypatch.setattr(ops.clusters, name + "_cluster", AsyncMock(return_value=row))
    return ctx, check, auth, row


@pytest.mark.parametrize("action", ["create", "update", "edit"])
async def test_manage_resolves_tenant_admin_and_filters_secrets(cluster, action):
    ctx, check, auth, row = cluster
    payload = {"action": action}
    if action != "create":
        payload["id"] = row.id
    if action != "edit":
        payload["data"] = {"name": row.name}
    response = await ops.write_cluster(ctx, payload, None)
    check.assert_awaited_once_with(ctx.db, ctx.user, "t", require_admin=True)
    command = getattr(ops.clusters, ("get" if action == "edit" else action) + "_cluster")
    assert command.await_args.args[-1] == auth
    assert response["item"]["provider_config"] == {"nodes": 2}
    assert "credentials_encrypted" not in response["item"]
    assert "provider_config" not in project_inventory_row(row, "t")
    with pytest.raises(OptionalBusinessError, match="another tenant"):
        project_inventory_row(row, "other")


async def test_delete_rechecks_tenant_admin_and_forbids_extra_selectors(cluster):
    ctx, check, auth, _ = cluster
    with pytest.raises(ValidationError):
        await ops.delete_cluster(ctx, {"id": "c", "tenant_id": "foreign"}, None)
    check.assert_not_called()
    assert await ops.delete_cluster(ctx, {"id": "c"}, None) == {}
    check.assert_awaited_once_with(ctx.db, ctx.user, "t", require_admin=True)
    ops.clusters.delete_cluster.assert_awaited_once_with("c", auth)


@pytest.mark.parametrize(
    ("operation", "handler", "payload", "admin"),
    [
        (runner_ops.list_pools, "list_cluster_acp_runner_pools", {"id": "c"}, False),
        (
            runner_ops.create_pool,
            "create_cluster_acp_runner_pool",
            {"id": "c", "data": {"name": "dev", "poolKey": "dev"}},
            True,
        ),
        (
            runner_ops.issue_token,
            "create_cluster_acp_runner_registration_token",
            {"id": "c", "pool_key": "dev", "data": {"expiresInHours": 1}},
            True,
        ),
    ],
)
async def test_runner_commands_use_original_tenant_authority(
    cluster, monkeypatch, operation, handler, payload, admin
):
    ctx, check, authority, _ = cluster
    monkeypatch.setattr(runner_ops, "require_tenant_access", check)
    monkeypatch.setattr(
        runner_ops,
        "cluster_application_authority_dependency_v2",
        ops.cluster_application_authority_dependency_v2,
    )
    row = Mock()
    row.model_dump.return_value = {"id": "record"}
    underlying = AsyncMock(return_value=row if admin else [row])
    monkeypatch.setattr(runner_ops.clusters, handler, underlying)
    with pytest.raises(ValidationError):
        await operation(ctx, {**payload, "tenant_id": "other"}, None)
    await operation(ctx, payload, None)
    check.assert_awaited_once_with(ctx.db, ctx.user, "t", require_admin=admin)
    assert underlying.await_args.args[0] == "c"
    assert underlying.await_args.args[-1] is authority
    row.model_dump.assert_called_once_with(mode="json", by_alias=True)
