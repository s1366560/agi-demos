"""Exercise the signed billing UI commands against the same authority as tenant HTTP."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import update

from plugins.business.billing.build import ROOT, build_release
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def account_app(test_app):
    await initialize_plugin_runtime_v2(test_app)
    try:
        yield test_app
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_project_package_reads_real_account_and_owner_changes_plan(
    account_app, async_client, test_project_db, test_tenant_db, test_user, test_db
):
    key = Ed25519PrivateKey.generate()
    account_app.state.plugin_marketplace_trusted_public_keys_v2 = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    raw = build_release(json.loads((ROOT / "plans.json").read_bytes()), version="1.1.0", signer=key)
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": test_tenant_db.id, "project_id": test_project_db.id}
    selection = {**scope, "archive_base64": base64.b64encode(raw).decode()}
    preview = (await async_client.post(base + "/inspect", json=selection)).json()
    recorded = await async_client.post(
        base + "/install", json={**selection, "approved_permissions": preview["permissions"]}
    )
    assert recorded.is_success, recorded.text
    assert (await async_client.post(base + "/memstack-billing/enable", json=scope)).is_success
    installed = await test_db.get(
        ProjectPluginInstallation, (scope["project_id"], "memstack-billing")
    )
    assert installed.active == "1.1.0"

    async def invoke(command, payload):
        return await async_client.post(
            base + "/memstack-billing/commands",
            json={
                **scope,
                "command_id": command,
                **({"payload": payload} if payload else {}),
                "expected_digest": preview["digest"],
            },
        )

    account = await invoke("tenant-account", {})
    assert account.is_success, account.text
    assert account.json()["tenant"]["plan"] == "free"
    assert account.json()["usage"]["projects"] == 1
    details = await invoke("billing-details", {})
    assert details.json()["membership_role"] == "owner"
    assert details.json()["invoices"] == []
    changed = await invoke("change-plan", {"plan": "pro"})
    assert changed.is_success, changed.text
    assert (await invoke("tenant-account", {})).json()["tenant"]["storage_limit"] == 100 * 1024**3
    assert (
        await invoke("change-plan", {"plan": "free", "tenant_id": "unrelated"})
    ).status_code in (400, 422)
    await test_db.execute(
        update(UserTenant)
        .where(UserTenant.user_id == test_user.id, UserTenant.tenant_id == test_tenant_db.id)
        .values(role="admin")
    )
    await test_db.commit()
    assert (await invoke("billing-details", {})).json()["membership_role"] == "admin"
    assert (await invoke("change-plan", {"plan": "free"})).status_code == 403
    assert (await invoke("tenant-account", {})).json()["tenant"]["plan"] == "pro"
