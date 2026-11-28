"""Exercise project approvals and per-operation cloud device admission over HTTP."""

import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from src.application.services.auth_service_v2 import AuthService
from src.application.services.cloud_login_session_service import CloudLoginSessionService
from src.host.identity.device_plugin_grants import router
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey,
    Project,
    User,
    UserProject,
    UserTenant,
)


async def _access_key(test_db, user_id, *, interactive):
    token = AuthService.generate_api_key()
    key = APIKey(
        id=str(uuid4()),
        user_id=user_id,
        name="device test",
        key_hash=AuthService.hash_api_key(token),
        is_active=True,
        permissions=["*"],
    )
    test_db.add(key)
    await test_db.flush()
    if interactive:
        await CloudLoginSessionService(test_db, secret=secrets.token_hex()).bind_access_key(
            user_id=user_id, access_api_key_id=key.id, auth_method="password"
        )
    await test_db.commit()
    return token


@pytest.fixture
async def endpoint(test_db, test_project_db, test_user):
    assert str(test_db.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    token = await _access_key(test_db, test_user.id, interactive=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: test_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        proof = secrets.token_urlsafe(32)
        fields = {
            "machine_id": "test-machine",
            "bundle_digest": "a" * 64,
            "generation_id": "b" * 64,
            "approved_permissions": ["tools.execute"],
        }
        approval = dict(
            **fields,
            user_id=test_user.id,
            permissions=["install", "invoke"],
            device_fingerprint="sha256:" + hashlib.sha256(proof.encode("ascii")).hexdigest(),
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
        yield (
            client,
            f"/api/v1/projects/{test_project_db.id}/device-plugin-grants",
            approval,
            dict(**fields, device_proof=proof, permission="install"),
        )


async def test_approve_install_invoke_revoke_and_reapprove(endpoint, caplog):
    caplog.set_level(logging.INFO, logger="plugin_audit")
    client, path, approval, check = endpoint
    assert (await client.post(path + "/check", json=check)).status_code == 403
    assert (await client.get(path + "/authority")).json() == {"can_manage": True}
    issued = await client.post(path + "/", json=approval)
    assert issued.status_code == 201, issued.text
    grant_id = issued.json()["grant_id"]
    assert (await client.post(path + "/", json=approval)).json()["grant_id"] == grant_id
    allowed = await client.post(path + "/check", json=check)
    assert allowed.status_code == 200
    assert allowed.json()["grant_id"] == grant_id and allowed.json()["allowed"]
    assert "device_proof" not in allowed.json()
    invocation = dict(check, permission="invoke", grant_id=grant_id)
    assert (await client.post(path + "/check", json=invocation)).status_code == 200
    for change in (
        {"machine_id": "elsewhere"},
        {"bundle_digest": "c" * 64},
        {"generation_id": "c" * 64},
        {"device_proof": secrets.token_urlsafe(32)},
        {"approved_permissions": ["host.admin"]},
        {"grant_id": None},
    ):
        assert (await client.post(path + "/check", json=invocation | change)).status_code == 403
    assert (await client.delete(path + "/" + grant_id)).status_code == 204
    assert (await client.post(path + "/check", json=invocation)).status_code == 403
    assert (await client.post(path + "/", json=approval)).json()["grant_id"] != grant_id
    assert (await client.post(path + "/check", json=invocation)).status_code == 403

    receipts = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "plugin_audit.project_package"
    ]
    approvals = [e for e in receipts if e["operation"] == "device.approve" and e["outcome"] == "ok"]
    assert approvals and all(
        e["actor_id"] == e["subject_id"] == approval["user_id"] for e in approvals
    )
    assert any(
        e["operation"] == "device.revoke" and e["digest"] == check["bundle_digest"]
        for e in receipts
    )
    assert any(e["operation"] == "device.check" and e["outcome"] == "error" for e in receipts)
    assert check["device_proof"] not in caplog.text
    assert grant_id not in json.dumps(receipts)


async def test_scope_membership_and_login_required(endpoint, test_db, test_project_db):
    client, path, approval, check = endpoint
    await test_db.execute(
        update(UserProject)
        .where(UserProject.project_id == test_project_db.id)
        .values(role="member")
    )
    await test_db.commit()
    assert (await client.get(path + "/authority")).json() == {"can_manage": False}
    assert (await client.post(path + "/", json=approval)).status_code == 403
    from src.infrastructure.adapters.secondary.persistence.models import UserSession

    await test_db.execute(update(UserSession).values(revoked_at=datetime.now(UTC)))
    await test_db.commit()
    assert (await client.post(path + "/check", json=check)).status_code == 401


async def test_changing_approved_operations_invalidates_old_grant_and_expiry_is_enforced(
    endpoint, test_db
):
    from src.infrastructure.adapters.secondary.persistence.device_plugin_grant_model import (
        DevicePluginGrant,
    )

    client, path, approval, check = endpoint
    assert (
        await client.post(path + "/", json=approval | {"user_id": str(uuid4())})
    ).status_code == 403
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    assert (await client.post(path + "/", json=approval | {"expires_at": past})).status_code == 422
    initial = (await client.post(path + "/", json=approval)).json()["grant_id"]
    narrowed = await client.post(path + "/", json=approval | {"permissions": ["install"]})
    replacement = narrowed.json()["grant_id"]
    assert replacement != initial
    for operation, grant in (("invoke", initial), ("install", initial), ("invoke", replacement)):
        rejected = await client.post(
            path + "/check", json=check | {"permission": operation, "grant_id": grant}
        )
        assert rejected.status_code == 403
    assert (await client.post(path + "/check", json=check)).json()["grant_id"] == replacement
    await test_db.execute(
        update(DevicePluginGrant)
        .where(DevicePluginGrant.id == replacement)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await test_db.commit()
    assert (await client.post(path + "/check", json=check)).status_code == 403
    assert (await client.delete(path + "/" + str(uuid4()))).status_code == 404


async def test_device_grant_rechecks_project_execution_role(endpoint, test_db, test_project_db):
    client, path, approval, check = endpoint
    issued = await client.post(path + "/", json=approval)
    assert issued.status_code == 201
    invocation = {**check, "permission": "invoke", "grant_id": issued.json()["grant_id"]}
    for role, status in (("member", 200), ("viewer", 403)):
        await test_db.execute(
            update(UserProject)
            .where(UserProject.project_id == test_project_db.id)
            .values(role=role)
        )
        await test_db.commit()
        assert (await client.post(path + "/check", json=check)).status_code == status
        assert (await client.post(path + "/check", json=invocation)).status_code == status


async def test_unbound_api_key_cannot_borrow_another_active_cloud_session(
    endpoint, test_db, test_user
):
    client, path, approval, check = endpoint
    long_lived_key = await _access_key(test_db, test_user.id, interactive=False)
    headers = {"Authorization": "Bearer " + long_lived_key}
    assert (await client.get(path + "/authority", headers=headers)).status_code == 401
    assert (await client.post(path + "/", json=approval, headers=headers)).status_code == 401
    issued = await client.post(path + "/", json=approval)
    assert issued.status_code == 201
    assert (await client.post(path + "/check", json=check, headers=headers)).status_code == 401
    assert (
        await client.delete(path + "/" + issued.json()["grant_id"], headers=headers)
    ).status_code == 401
    assert (await client.post(path + "/check", json=check)).status_code == 200


async def test_only_granted_member_can_invoke_and_only_manager_can_revoke(
    endpoint, test_db, test_project_db
):
    client, path, approval, check = endpoint
    member = User(
        id=str(uuid4()), email="member@example.org", hashed_password="unused", is_active=True
    )
    test_db.add(member)
    await test_db.flush()
    test_db.add_all(
        [
            UserTenant(
                id=str(uuid4()),
                user_id=member.id,
                tenant_id=test_project_db.tenant_id,
                role="member",
            ),
            UserProject(
                id=str(uuid4()), user_id=member.id, project_id=test_project_db.id, role="member"
            ),
        ]
    )
    token = await _access_key(test_db, member.id, interactive=True)
    headers = {"Authorization": "Bearer " + token}
    approved = await client.post(path + "/", json=approval | {"user_id": member.id})
    assert approved.status_code == 201 and approved.json()["user_id"] == member.id
    grant = approved.json()["grant_id"]
    invoke = check | {"permission": "invoke", "grant_id": grant}
    assert (await client.post(path + "/check", json=invoke)).status_code == 403
    admitted = await client.post(path + "/check", json=invoke, headers=headers)
    assert admitted.status_code == 200 and admitted.json()["user_id"] == member.id
    assert admitted.headers["Cache-Control"] == "no-store"
    assert (await client.delete(path + "/" + grant, headers=headers)).status_code == 403
    member.is_active = False
    await test_db.commit()
    assert (
        await client.post(path + "/", json=approval | {"user_id": member.id})
    ).status_code == 403


async def test_grant_cannot_cross_managed_projects_and_double_revoke_is_idempotent(
    endpoint, test_db, test_project_db, test_user
):
    from src.infrastructure.adapters.secondary.persistence.device_plugin_grant_model import (
        DevicePluginGrant,
    )

    client, path, approval, check = endpoint
    second = Project(
        id=str(uuid4()),
        name="Separate project",
        tenant_id=test_project_db.tenant_id,
        owner_id=test_user.id,
    )
    test_db.add(second)
    await test_db.flush()
    test_db.add(
        UserProject(id=str(uuid4()), user_id=test_user.id, project_id=second.id, role="owner")
    )
    await test_db.commit()
    other = f"/api/v1/projects/{second.id}/device-plugin-grants"
    assert (await client.get(other + "/authority")).json() == {"can_manage": True}
    missing = f"/api/v1/projects/{uuid4()}/device-plugin-grants"
    assert (await client.get(missing + "/authority")).status_code == 403
    grant = (await client.post(path + "/", json=approval)).json()["grant_id"]
    invoke = check | {"grant_id": grant, "permission": "invoke"}
    assert (await client.post(other + "/check", json=invoke)).status_code == 403
    assert (await client.delete(other + "/" + grant)).status_code == 404
    assert (await client.post(path + "/check", json=invoke)).status_code == 200
    assert (await client.delete(path + "/" + grant)).status_code == 204
    row = await test_db.get(DevicePluginGrant, grant, populate_existing=True)
    when_revoked = row.revoked_at
    assert when_revoked is not None
    assert (await client.delete(path + "/" + grant)).status_code == 204
    await test_db.refresh(row)
    assert row.revoked_at == when_revoked
    assert (await client.post(path + "/check", json=invoke)).status_code == 403


async def test_grant_is_fenced_by_active_release_and_epoch(endpoint, test_db, test_project_db):
    from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
        ProjectPluginInstallation,
        ProjectPluginRelease,
    )

    client, path, approval, check = endpoint
    plugin = "selected-device"
    project = test_project_db.id
    for version, digest in (("1", "a"), ("2", "c")):
        test_db.add(
            ProjectPluginRelease(
                project_id=project,
                tenant_id=test_project_db.tenant_id,
                plugin_id=plugin,
                version=version,
                digest=f"sha256:{digest * 64}",
                permissions=["tools.execute"],
                archive=b"test",
                approved_by=approval["user_id"],
            )
        )
    recorded = ProjectPluginInstallation(
        project_id=project,
        plugin_id=plugin,
        desired="1",
        active="1",
        enabled=True,
    )
    test_db.add(recorded)
    await test_db.commit()
    response = await client.get(path + "/selection", params={"plugin_id": plugin})
    assert response.status_code == 200
    generation = response.json()["generation_id"]
    assert generation.startswith("p")
    assert (await client.post(path + "/", json=approval)).status_code == 403
    grant = await client.post(path + "/", json=approval | {"generation_id": generation})
    assert grant.status_code == 201, grant.text
    invoke = check | {
        "generation_id": generation,
        "permission": "invoke",
        "grant_id": grant.json()["grant_id"],
    }
    assert (await client.post(path + "/check", json=invoke)).status_code == 200
    for enabled, active in ((True, "2"), (False, "1"), (True, "1")):
        await test_db.execute(
            update(ProjectPluginInstallation)
            .where(ProjectPluginInstallation.project_id == project)
            .values(
                enabled=enabled,
                active=active,
                generation=ProjectPluginInstallation.generation + 1,
                authorization_epoch=ProjectPluginInstallation.authorization_epoch + 1,
            )
        )
        await test_db.commit()
        assert (await client.post(path + "/check", json=invoke)).status_code == 403
        assert (
            await client.post(path + "/", json=approval | {"generation_id": generation})
        ).status_code == 403
