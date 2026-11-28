"""A tenant can approve and run its signed billing page before creating a project."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import update

from plugins.business.billing.build import ROOT, build_release
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation import (
    TenantPluginRelease,
)
from src.tests.unit.routers.test_signed_tenant_account import account_app as _account_app

account_app = _account_app
pytestmark = pytest.mark.unit
BASE = "/api/v1/tenant-packages"
BILLING = BASE + "/memstack-billing"


async def test_independent_billing_approval_before_first_project(
    account_app, async_client, test_tenant_db, test_user, test_db
):
    key = Ed25519PrivateKey.generate()
    account_app.state.plugin_marketplace_trusted_public_keys_v2 = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    scope = {"tenant_id": test_tenant_db.id}
    api = async_client
    assert (await api.get(BASE + "/tenants")).json()["items"][0]["can_manage"]
    assert not (await api.get(BASE + "/", params=scope)).json()["items"]
    assert (await api.get(BASE + "/", params={"tenant_id": "other"})).status_code == 403

    async def select_release(version, rev):
        raw = build_release(
            json.loads((ROOT / "plans.json").read_text()),
            version=version,
            signer=key,
            worker_image="localhost:5000/billing@sha256:" + "a" * 64,
        )
        body = {**scope, "archive_base64": base64.b64encode(raw).decode()}
        inspected = await api.post(BASE + "/inspect", json=body)
        assert inspected.is_success, inspected.text
        release = inspected.json()
        assert set(release["permissions"]) == {
            "ui.slot",
            "app.billing.account.read",
            "app.billing.plan.write",
        }
        approved = {
            **body,
            "expected_revision": rev,
            "expected_digest": release["digest"],
            "approved_permissions": release["permissions"],
        }
        assert (
            await api.post(
                BASE + "/install", json={**approved, "expected_digest": "sha256:" + "0" * 64}
            )
        ).status_code == 409
        assert (
            await api.post(BASE + "/install", json={**approved, "approved_permissions": []})
        ).status_code == 403
        response = await api.post(BASE + "/install", json=approved)
        assert response.is_success, response.text
        assert (await api.post(BASE + "/install", json=approved)).status_code == 409
        enabled = await api.post(
            BILLING + "/enable",
            json={**scope, "expected_revision": response.json()["desired_revision"]},
        )
        assert enabled.is_success, enabled.text
        return enabled.json()

    a = await select_release("1.2.0", 0)
    b = await select_release("1.2.1", a["desired_revision"])
    approved = await test_db.get(
        TenantPluginRelease, (scope["tenant_id"], "memstack-billing", "1.2.1")
    )
    assert approved.approved_by == test_user.id
    entry = (await api.get(BASE + "/", params=scope)).json()["items"][0]
    assert (entry["status"], entry["scope"], entry["actual_digest"]) == (
        "enabled",
        "tenant",
        b["actual_digest"],
    )
    await assert_shared_tenant_account_page(api, scope, b)

    async def command(digest, name, payload=None):
        return await api.post(
            BILLING + "/commands",
            json={**scope, "expected_digest": digest, "command_id": name, "payload": payload},
        )

    assert (await command(b["actual_digest"], "list-invoices")).status_code == 403
    account = await command(b["actual_digest"], "billing-details")
    assert account.is_success, account.text
    assert account.json()["usage"]["projects"] == 0
    changed = await command(b["actual_digest"], "change-plan", {"plan": "pro"})
    assert changed.is_success, changed.text
    assert (await command(a["actual_digest"], "billing-details")).status_code == 409
    restored = await api.post(
        BILLING + "/rollback", json={**scope, "expected_revision": b["desired_revision"]}
    )
    assert restored.json()["actual_digest"] == a["actual_digest"]
    assert (await command(a["actual_digest"], "billing-details")).json()["tenant"]["plan"] == "pro"
    await test_db.execute(
        update(UserTenant)
        .where(UserTenant.user_id == test_user.id, UserTenant.tenant_id == test_tenant_db.id)
        .values(role="viewer")
    )
    await test_db.commit()
    assert (await api.get(BILLING, params=scope)).is_success
    assert (await command(a["actual_digest"], "billing-details")).status_code == 403
    assert (
        await api.post(
            BILLING + "/uninstall",
            json={**scope, "expected_revision": restored.json()["desired_revision"]},
        )
    ).status_code == 403


async def assert_shared_tenant_account_page(api, scope, release):
    assert {(p["id"], tuple(p["targets"])) for p in release["pages"]} == {
        ("tenant-account", ("desktop-renderer", "web")),
    }
    params = {
        **scope,
        "target": "web",
        "expected_digest": release["actual_digest"],
        "page_id": "tenant-account",
    }
    web = (await api.get(BILLING + "/ui", params=params)).json()
    desktop = (
        await api.get(BILLING + "/ui", params={**params, "target": "desktop-renderer"})
    ).json()
    assert web["scope"] == desktop["scope"] == "tenant"
    assert web["entry"] == desktop["entry"]
    assert web["style"] == desktop["style"]
    assert (
        await api.get(BILLING + "/ui", params={**params, "page_id": "account"})
    ).status_code == 404
