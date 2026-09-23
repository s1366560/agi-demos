"""Scoped cache retention, expiry and guarded physical removal."""

from __future__ import annotations

import base64
import copy
import shlex
import subprocess
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_snapshot_cache import (
    MarketplaceSnapshotCache,
    lease_marketplace_snapshots,
    preflight_expiry,
    require_fresh_preflight,
    validate_runtime_root,
)

pytestmark = pytest.mark.unit
DIGEST = "a" * 64
PACKAGE = {"digest": DIGEST, "files": {"README.md": base64.b64encode(b"demo").decode()}}
ROOT = f"/workspace/.memstack/plugins/{uuid4()}/{DIGEST}"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(MarketplaceRecordV3.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def record(db, kind, payload, tenant="tenant", project="project"):
    row = MarketplaceRecordV3(
        id=str(uuid4()),
        tenant_id=tenant,
        project_id=project,
        kind=kind,
        record_key=str(uuid4()),
        payload=payload,
    )
    db.add(row)
    await db.flush()
    return row


def test_preflight_has_exact_day_ttl_and_missing_or_expired_is_rejected():
    assert preflight_expiry(10) == 86410
    require_fresh_preflight({"expires_at": 11}, 10)
    for payload in ({}, {"expires_at": 10}, {"expires_at": 9}, {"expires_at": "never"}):
        with pytest.raises(ValueError, match="expired"):
            require_fresh_preflight(payload, 10)


@pytest.mark.parametrize(
    "root",
    [
        "/workspace",
        ROOT + "/..",
        ROOT.replace(DIGEST, "../outside"),
        ROOT.replace("/plugins/", "/other/"),
        ROOT.replace(DIGEST, "g" * 64),
    ],
)
def test_rejects_unowned_or_malformed_snapshot_paths(root):
    with pytest.raises(ValueError):
        validate_runtime_root(root)


async def test_live_installation_and_valid_preflight_protect_cache_and_tenant_isolation(db):
    cache = MarketplaceSnapshotCache(db, "tenant", "project")
    await cache.register(PACKAGE)
    await cache.register(PACKAGE, ROOT)
    await record(db, "preflight", {"package": PACKAGE, "expires_at": preflight_expiry()})
    installation = await record(
        db, "installation", {"status": "disabled", "package": PACKAGE, "runtime_root": ROOT}
    )
    assert await cache.stats() == {"total_bytes": 8, "reclaimable_bytes": 0, "entries": 2}
    assert (await cache.cleanup("keep"))["removed_bytes"] == 0
    other = MarketplaceSnapshotCache(db, "other", "project")
    assert (await other.stats())["entries"] == 0
    assert (await other.cleanup("keep"))["removed_entries"] == 0
    assert installation.payload["package"]["files"]


async def test_expired_uninstalled_bytes_removed_once_without_deleting_metadata(db):
    cache = MarketplaceSnapshotCache(db, "tenant", "project")
    await cache.register(PACKAGE)
    preview = await record(db, "preflight", {"package": copy.deepcopy(PACKAGE), "expires_at": 1})
    installation = await record(
        db, "installation", {"status": "uninstalled", "package": copy.deepcopy(PACKAGE)}
    )
    first = await cache.cleanup("cleanup-1")
    assert first == {
        "total_bytes": 0,
        "reclaimable_bytes": 0,
        "entries": 0,
        "removed_bytes": 4,
        "removed_entries": 1,
    }
    assert preview.payload["package"]["files"] == {}
    assert installation.payload["package"]["digest"] == DIGEST
    assert await cache.cleanup("cleanup-1") == first


async def test_failed_sandbox_removal_preserves_pending_registration_for_retry(db):
    sandbox = AsyncMock()
    sandbox.execute_tool.return_value = {"isError": True}
    cache = MarketplaceSnapshotCache(db, "tenant", "project", sandbox)
    snapshot_id = await cache.register(PACKAGE, ROOT)
    with pytest.raises(ValueError, match="retained"):
        await cache.cleanup("cleanup")
    assert (await db.get(MarketplaceRecordV3, snapshot_id)).payload[
        "state"
    ] == "pending_reclamation"
    sandbox.execute_tool.return_value = {"metadata": {"exit_code": 0}}
    assert (await cache.cleanup("cleanup"))["removed_bytes"] == 4
    assert await db.get(MarketplaceRecordV3, snapshot_id) is None


async def test_guarded_removal_rejects_symlink_ancestor_and_preserves_other_files(db, tmp_path):
    workspace = tmp_path / "workspace"
    owned = workspace / ".memstack" / "plugins"
    owned.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "preserve.txt"
    marker.write_text("untouched")
    installation_id = ROOT.split("/")[-2]
    (owned / installation_id).symlink_to(outside, target_is_directory=True)

    async def run(**kwargs):
        command = kwargs["arguments"]["command"].replace("/workspace", str(workspace))
        result = subprocess.run(shlex.split(command), capture_output=True, check=False)
        return {"metadata": {"exit_code": result.returncode}}

    sandbox = AsyncMock()
    sandbox.execute_tool.side_effect = run
    cache = MarketplaceSnapshotCache(db, "tenant", "project", sandbox)
    await cache.register(PACKAGE, ROOT)
    with pytest.raises(ValueError, match="retained"):
        await cache.cleanup("cleanup")
    assert marker.read_text() == "untouched"
    assert (
        len(
            list(
                await db.scalars(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "snapshot")
                )
            )
        )
        == 1
    )


async def test_pending_reclamation_cannot_be_leased_and_context_releases_on_failure(db):
    cache = MarketplaceSnapshotCache(db, "tenant", "project")
    snapshot_id = await cache.register(PACKAGE, ROOT)
    await db.commit()
    async with lease_marketplace_snapshots(db, "tenant", "project", runtime_root=ROOT):
        assert (await db.get(MarketplaceRecordV3, snapshot_id)).payload["state"] == "retained"
    row = await db.get(MarketplaceRecordV3, snapshot_id)
    row.payload = {**row.payload, "state": "pending_reclamation"}
    await db.commit()
    with pytest.raises(ValueError, match="reclaimed"):
        async with lease_marketplace_snapshots(db, "tenant", "project", runtime_root=ROOT):
            pytest.fail("pending snapshot must not execute")
