"""Startup retries reclaim only registered, unreferenced marketplace snapshots."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.services.marketplace_cache_recovery import MarketplaceCacheRecovery
from src.infrastructure.adapters.secondary.persistence.models import Project, ProjectSandbox
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_snapshot_cache import MarketplaceSnapshotCache

pytestmark = pytest.mark.unit


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(MarketplaceRecordV3.__table__.create)
        await connection.run_sync(Project.__table__.create)
        await connection.run_sync(ProjectSandbox.__table__.create)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_startup_removes_registered_orphan_and_expired_preview_only(sessions):
    async with sessions() as db:
        cache = MarketplaceSnapshotCache(db, "tenant", "")
        await cache.register({"digest": "orphan", "files": {"demo.txt": "ZGVtbw=="}})
        await cache.register({"digest": "active", "files": {"demo.txt": "ZGVtbw=="}})
        db.add(
            MarketplaceRecordV3(
                id="active",
                tenant_id="tenant",
                project_id="",
                kind="installation",
                record_key="active",
                payload={"id": "active", "status": "enabled", "package": {"digest": "active"}},
            )
        )
        await db.commit()
    host = AsyncMock()
    recovery = MarketplaceCacheRecovery(sessions, host)
    await recovery.run_once()
    async with sessions() as db:
        records = list(
            await db.scalars(
                select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "snapshot")
            )
        )
        assert [row.payload["digest"] for row in records] == ["active"]
    host.acquire.assert_not_called()


async def test_start_runs_immediately_and_stop_owns_background_task(sessions):
    recovery = MarketplaceCacheRecovery(sessions, AsyncMock(), interval=0.01)
    called = asyncio.Event()
    recovery.run_once = AsyncMock(side_effect=lambda: called.set())
    recovery.start()
    task = recovery.task
    recovery.start()
    assert recovery.task is task
    await asyncio.wait_for(called.wait(), 1)
    await recovery.stop()
    assert task.done()
    assert recovery.task is None


@pytest.fixture
async def runtime_host():
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.tests.unit.infrastructure.plugins.v2.test_sandbox_operation_services_v2 import (
        _RedisCacheClient,
        _TrackedSandboxAdapter,
    )

    adapter = _TrackedSandboxAdapter()
    adapter.call_tool = AsyncMock(return_value={"content": []})
    adapter.create_sandbox = AsyncMock(side_effect=AssertionError("Recovery must not allocate"))
    root = Path(__file__).resolve().parents[5]
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            sandbox_runtime_factory=lambda: adapter,
            sandbox_redis_client=_RedisCacheClient(),
        )
    )
    publication = await host.bootstrap(
        profile_path=root / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(root / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=83,
        version=83,
    )
    assert publication.accepted
    try:
        yield host, adapter
    finally:
        await host.close()


async def seed_project(sessions, tenant, project, *, sandbox_tenant=None, status="running"):
    root = f"/workspace/.memstack/plugins/{uuid4()}/" + "a" * 64
    async with sessions() as db:
        db.add(Project(id=project, tenant_id=tenant, name=project, owner_id="user"))
        if status is not None:
            db.add(
                ProjectSandbox(
                    id=str(uuid4()),
                    project_id=project,
                    tenant_id=sandbox_tenant or tenant,
                    sandbox_id=f"sandbox-{project}",
                    status=status,
                )
            )
        await MarketplaceSnapshotCache(db, tenant, project).register(
            {"digest": "same-digest", "files": {"demo": "ZGVtbw=="}}, root
        )
        await db.commit()
    return root


async def test_real_root_provider_recovers_only_exact_project_without_internal_commit(
    sessions, runtime_host, monkeypatch
):
    from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
        SqlProjectSandboxRepository,
    )

    host, adapter = runtime_host
    root_a = await seed_project(sessions, "tenant-a", "project-a")
    await seed_project(sessions, "tenant-b", "project-b")
    writes = []
    original = SqlProjectSandboxRepository._finish_write

    async def finish_write(repository):
        writes.append(repository._commit_on_write)
        await original(repository)

    monkeypatch.setattr(SqlProjectSandboxRepository, "_finish_write", finish_write)
    recovery = MarketplaceCacheRecovery(sessions, host)
    await recovery.recover_scope("tenant-a", "project-b")
    adapter.call_tool.assert_not_awaited()
    await recovery.recover_scope("tenant-a", "project-a")
    adapter.call_tool.assert_awaited_once()
    call = adapter.call_tool.call_args.kwargs
    assert call["sandbox_id"] == "sandbox-project-a"
    assert root_a in call["arguments"]["command"]
    assert writes == [False]
    adapter.create_sandbox.assert_not_awaited()
    async with sessions() as db:
        snapshots = list(await db.scalars(select(MarketplaceRecordV3)))
        assert [(row.tenant_id, row.project_id) for row in snapshots] == [("tenant-b", "project-b")]


@pytest.mark.parametrize(
    "status,sandbox_tenant", [(None, None), ("running", "other"), ("stopped", None)]
)
async def test_missing_foreign_or_stopped_sandbox_keeps_registered_root(
    sessions, runtime_host, status, sandbox_tenant
):
    host, adapter = runtime_host
    await seed_project(sessions, "tenant", "project", status=status, sandbox_tenant=sandbox_tenant)
    await MarketplaceCacheRecovery(sessions, host).run_once()
    adapter.call_tool.assert_not_awaited()
    adapter.create_sandbox.assert_not_awaited()
    async with sessions() as db:
        row = await db.scalar(select(MarketplaceRecordV3))
        assert row is not None
        assert row.payload["state"] == "pending_reclamation"


async def test_failed_scope_retains_attempt_and_next_pass_retries_without_blocking_others(
    sessions, runtime_host
):
    host, adapter = runtime_host
    await seed_project(sessions, "tenant-a", "project-a")
    await seed_project(sessions, "tenant-b", "project-b")

    async def execute(**kwargs):
        if kwargs["sandbox_id"] == "sandbox-project-a":
            raise ConnectionError("sandbox offline")
        return {"content": []}

    adapter.call_tool.side_effect = execute
    recovery = MarketplaceCacheRecovery(sessions, host)
    await recovery.run_once()
    async with sessions() as db:
        remaining = list(await db.scalars(select(MarketplaceRecordV3)))
        assert len(remaining) == 1
        assert remaining[0].project_id == "project-a"
        assert remaining[0].payload["cleanup_attempts"] == 1
        assert remaining[0].payload["cleanup_error"] == "snapshot_cleanup_deferred"
    adapter.call_tool.side_effect = None
    await recovery.run_once()
    async with sessions() as db:
        assert await db.scalar(select(MarketplaceRecordV3)) is None
    assert adapter.call_tool.await_count == 3
    adapter.create_sandbox.assert_not_awaited()
