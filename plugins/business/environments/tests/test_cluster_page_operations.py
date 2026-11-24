from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.environments.backend import cluster_operations as ops
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
