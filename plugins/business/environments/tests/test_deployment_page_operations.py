from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugins.business.environments.backend import (
    deploy_operations as deploys,
    instance_template_operations as templates,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("op", "body"),
    [
        (deploys.read_deploys, {"view": "detail", "id": "foreign"}),
        (deploys.change_deploy, {"action": "cancel", "id": "foreign"}),
        (deploys.change_deploy, {"action": "create", "id": "foreign"}),
    ],
)
async def test_deploy_scope_checked_before_returning_or_changing_record(monkeypatch, op, body):
    ctx = SimpleNamespace(
        request=object(), user=object(), db=object(), scope=SimpleNamespace(tenant_id="selected")
    )
    access = AsyncMock()
    monkeypatch.setattr(deploys, "require_tenant_access", access)

    async def authority(*args):
        yield SimpleNamespace(
            services=SimpleNamespace(
                access=SimpleNamespace(
                    find_instance_tenant_id=AsyncMock(return_value="other"),
                    find_deploy_tenant_id=AsyncMock(return_value="other"),
                )
            )
        )

    monkeypatch.setattr(deploys, "deploy_application_authority_dependency_v2", authority)
    with pytest.raises(OptionalBusinessError):
        await op(ctx, body, None)
    access.assert_awaited_once_with(ctx.db, ctx.user, "selected")


@pytest.mark.parametrize(
    "wrong", [{"tenant_id": "other"}, {"cluster_id": "foreign"}, {"workspace_id": "foreign"}]
)
async def test_tenant_instance_wizard_cannot_attach_resources_outside_authority(monkeypatch, wrong):
    ctx = SimpleNamespace(
        request=object(),
        user=object(),
        db=SimpleNamespace(scalar=AsyncMock(return_value=None)),
        scope=SimpleNamespace(tenant_id="selected"),
    )
    access = AsyncMock()
    monkeypatch.setattr(templates, "require_tenant_access", access)
    with pytest.raises(OptionalBusinessError):
        await templates.create_instance(
            ctx, {"name": "A", "slug": "a", "tenant_id": "selected", **wrong}, None
        )
    access.assert_awaited_once_with(ctx.db, ctx.user, "selected")
