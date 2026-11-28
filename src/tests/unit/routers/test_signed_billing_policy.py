"""Publish signed quotes through the real billing HTTP router and authentication dependency."""

import hashlib
import secrets
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import update

from plugins.business.billing.backend import policy
from plugins.business.billing.build import build_release, compile_guest
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_from_header_or_query,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey, UserTenant
from src.infrastructure.plugins.v2.billing_services import BILLING_PROVIDER_MODULE_V2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2

pytestmark = pytest.mark.unit


async def _publish(app, digest, version):
    current = app.state.platform_plugin_runtime_v2.current_distribution
    config = {"strategy": "operation-async-session"}
    if digest is not None:
        config["policy_archive_digest"] = digest
    snapshot = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=current.snapshot.profile_id,
            entries=tuple(
                replace(entry, config=config)
                if entry.module_ref == BILLING_PROVIDER_MODULE_V2
                else entry
                for entry in current.snapshot.entries
            ),
        ),
        {m.plugin_id: m for m in current.snapshot.manifests},
        generation=version,
    )
    result = await app.state.platform_plugin_http_route_publication_v2.publish_snapshot(
        snapshot, control_envelope_v2(snapshot, version=version)
    )
    return result.plugin_publication


async def test_authenticated_upgrade_follows_signed_policy_across_update_failure_and_rollback(
    test_app, async_client, test_db, test_tenant_db, test_user, tmp_path, monkeypatch
):
    from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path

    ensure_plugin_sdk_path()
    key = Ed25519PrivateKey.generate()
    public = tmp_path / "publisher.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = policy.get_settings().model_copy(
        update={
            "billing_policy_archive_directory": tmp_path,
            "plugin_marketplace_trusted_key_files": (public,),
        }
    )
    monkeypatch.setattr(policy, "get_settings", lambda: settings)
    archive = build_release({"pro": 456}, version="3.1.0", signer=key)
    digest = hashlib.sha256(archive).hexdigest()
    (tmp_path / f"{digest}.zip").write_bytes(archive)
    token = "ms_sk_" + secrets.token_hex(32)
    test_db.add(
        APIKey(
            id=str(uuid4()),
            user_id=test_user.id,
            name="isolated-test",
            key_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
    )
    await test_db.commit()
    test_app.dependency_overrides.pop(get_current_user)
    test_app.dependency_overrides.pop(get_current_user_from_header_or_query)
    await initialize_plugin_runtime_v2(test_app)
    url = f"/api/v1/tenants/{test_tenant_db.id}/upgrade"
    headers = {"Authorization": f"Bearer {token}"}

    async def upgrade():
        result = await async_client.post(url, json={"plan": "pro"}, headers=headers)
        assert result.status_code == 200, result.text
        return result.json()["tenant"]["storage_limit"]

    try:
        assert (await async_client.post(url, json={"plan": "pro"})).status_code == 401
        assert await upgrade() == 100 * 1024**3
        assert (await _publish(test_app, f"sha256:{digest}", 71)).accepted
        assert await upgrade() == 456
        # A signed archive from another publisher cannot replace this tenant's quota worker.
        rejected = build_release({"pro": 999}, version="3.2.0", signer=Ed25519PrivateKey.generate())
        bad_digest = hashlib.sha256(rejected).hexdigest()
        (tmp_path / f"{bad_digest}.zip").write_bytes(rejected)
        assert not (await _publish(test_app, f"sha256:{bad_digest}", 72)).accepted
        assert await upgrade() == 456
        assert (await _publish(test_app, None, 73)).accepted
        assert await upgrade() == 100 * 1024**3
        await test_db.execute(
            update(UserTenant)
            .where(UserTenant.user_id == test_user.id, UserTenant.tenant_id == test_tenant_db.id)
            .values(role="admin")
        )
        await test_db.commit()
        assert (
            await async_client.post(url, json={"plan": "pro"}, headers=headers)
        ).status_code == 403
    finally:
        await shutdown_plugin_runtime_v2(test_app)


def test_shipped_guest_is_reproducible_from_package_catalog():
    import json

    root = Path(policy.__file__).resolve().parents[1]
    assert (
        compile_guest(json.loads((root / "plans.json").read_bytes()))
        == (root / "quote.wasm").read_bytes()
    )
