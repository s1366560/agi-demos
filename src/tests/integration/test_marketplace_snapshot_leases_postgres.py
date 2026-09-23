"""Real PostgreSQL leases survive independent cleanup and reclaim on final release."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_snapshot_cache import (
    MarketplaceSnapshotCache,
    lease_marketplace_snapshots,
)

pytestmark = pytest.mark.integration
pytest_plugins = ("src.tests.integration.test_marketplace_v3_jobs_postgres",)


async def test_cleanup_skips_running_snapshot_then_final_lease_reclaims_files_and_grants(sessions):
    owner = str(uuid4())
    digest = "a" * 64
    root = f"/workspace/.memstack/plugins/{owner}/{digest}"
    sandbox = AsyncMock()
    sandbox.execute_tool.return_value = {"metadata": {"exit_code": 0}}
    async with sessions() as setup:
        await MarketplaceSnapshotCache(setup, "tenant", "project").register(
            {"digest": digest, "files": {"file": base64.b64encode(b"data").decode()}},
            root,
            owner_id=owner,
        )
        setup.add(
            MarketplaceRecordV3(
                id=owner,
                tenant_id="tenant",
                project_id="project",
                kind="installation",
                record_key=owner,
                payload={
                    "status": "uninstalled",
                    "runtime_root": root,
                    "package": {"digest": digest},
                },
            )
        )
        for kind in ("oauth_grant", "oauth_challenge", "oauth_request"):
            setup.add(
                MarketplaceRecordV3(
                    id=str(uuid4()),
                    tenant_id="tenant",
                    project_id="project",
                    kind=kind,
                    record_key=kind,
                    payload={"installation_id": owner, "sealed": "fixture-ciphertext"},
                )
            )
        await setup.commit()
    async with sessions() as caller:
        async with (
            lease_marketplace_snapshots(
                caller, "tenant", "project", runtime_root=root, sandbox=sandbox
            ),
            sessions() as cleanup,
        ):
            result = await MarketplaceSnapshotCache(cleanup, "tenant", "project", sandbox).cleanup(
                "while-running"
            )
            await cleanup.commit()
            assert result["removed_entries"] == 0
            sandbox.execute_tool.assert_not_called()
            assert (
                await cleanup.scalar(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "oauth_grant")
                )
                is not None
            )
        async with sessions() as verification:
            assert (
                await verification.scalar(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "snapshot")
                )
                is None
            )
            assert (
                await verification.scalar(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "oauth_grant")
                )
                is None
            )
            assert (
                await verification.scalar(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "oauth_challenge")
                )
                is None
            )
            assert (
                await verification.scalar(
                    select(MarketplaceRecordV3).where(MarketplaceRecordV3.kind == "oauth_request")
                )
                is None
            )
        sandbox.execute_tool.assert_awaited_once()


async def test_busy_installation_reference_defers_cleanup_without_deadlocking(sessions):
    owner = str(uuid4())
    root = f"/workspace/.memstack/plugins/{owner}/{'b' * 64}"
    async with sessions() as setup:
        await MarketplaceSnapshotCache(setup, "tenant", "project").register(
            {"digest": "b" * 64, "files": {}}, root, owner_id=owner
        )
        setup.add(
            MarketplaceRecordV3(
                id=owner,
                tenant_id="tenant",
                project_id="project",
                kind="installation",
                record_key=owner,
                payload={
                    "status": "uninstalled",
                    "runtime_root": root,
                    "package": {"digest": "b" * 64},
                },
            )
        )
        await setup.commit()
    async with sessions() as mutation:
        await mutation.scalar(
            select(MarketplaceRecordV3).where(MarketplaceRecordV3.id == owner).with_for_update()
        )
        async with sessions() as cleanup:
            result = await asyncio.wait_for(
                MarketplaceSnapshotCache(cleanup, "tenant", "project", AsyncMock()).cleanup("busy"),
                1.0,
            )
            assert result["removed_entries"] == 0
            await cleanup.commit()
        await mutation.rollback()


async def test_secret_locked_by_call_is_purged_after_call_transaction_ends(sessions):
    owner = str(uuid4())
    root = f"/workspace/.memstack/plugins/{owner}/{'c' * 64}"
    grant_id = str(uuid4())
    sandbox = AsyncMock()
    sandbox.execute_tool.return_value = {"metadata": {"exit_code": 0}}
    async with sessions() as setup:
        await MarketplaceSnapshotCache(setup, "tenant", "project").register(
            {"digest": "c" * 64, "files": {}}, root, owner_id=owner
        )
        setup.add(
            MarketplaceRecordV3(
                id=owner,
                tenant_id="tenant",
                project_id="project",
                kind="installation",
                record_key=owner,
                payload={
                    "status": "uninstalled",
                    "runtime_root": root,
                    "package": {"digest": "c" * 64},
                },
            )
        )
        setup.add(
            MarketplaceRecordV3(
                id=grant_id,
                tenant_id="tenant",
                project_id="project",
                kind="oauth_grant",
                record_key=grant_id,
                payload={"installation_id": owner, "sealed": "fixture-ciphertext"},
            )
        )
        await setup.commit()
    async with sessions() as caller:
        await caller.scalar(
            select(MarketplaceRecordV3).where(MarketplaceRecordV3.id == grant_id).with_for_update()
        )
        async with lease_marketplace_snapshots(
            caller, "tenant", "project", runtime_root=root, sandbox=sandbox
        ):
            pass
        async with sessions() as verification:
            assert await verification.get(MarketplaceRecordV3, grant_id) is not None
        await caller.commit()
        for _ in range(30):
            async with sessions() as verification:
                if await verification.get(MarketplaceRecordV3, grant_id) is None:
                    break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("last request transaction did not release dedicated credential state")


async def test_activation_verification_reuses_own_snapshot_transaction_without_deadlock(sessions):
    owner = str(uuid4())
    root = f"/workspace/.memstack/plugins/{owner}/{'d' * 64}"
    async with sessions() as mutation:
        mutation.info["marketplace_transaction_owned"] = True
        await MarketplaceSnapshotCache(mutation, "tenant", "project").register(
            {"digest": "d" * 64, "files": {}}, root, owner_id=owner
        )

        async def verify():
            async with lease_marketplace_snapshots(
                mutation, "tenant", "project", runtime_root=root
            ):
                return "verified"

        assert await asyncio.wait_for(verify(), 1.0) == "verified"
        await mutation.rollback()


async def test_remote_hook_process_survives_database_lease_and_blocks_snapshot_cleanup(sessions):
    import json
    import os
    import subprocess

    container = os.environ.get("MARKETPLACE_TEST_SANDBOX_CONTAINER")
    if not container:
        pytest.skip("requires an explicitly task-owned Linux sandbox container")
    owner = str(uuid4())
    root = f"/workspace/.memstack/plugins/{owner}/{'e' * 64}"
    setup_script = "\n".join(
        [
            "import pathlib, subprocess, sys",
            f"p = pathlib.Path({root!r}); p.mkdir(parents=True)",
            '(p / "slow_hook.py").write_text("import time; time.sleep(60)")',
            'child = subprocess.Popen([sys.executable, str(p / "slow_hook.py")], cwd=p, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)',
            "print(child.pid)",
        ]
    )
    child_pid = int(
        subprocess.check_output(
            ["docker", "exec", container, "python3", "-c", setup_script], text=True
        ).strip()
    )
    sandbox = AsyncMock()

    async def remote(**kwargs):
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "exec", container, "sh", "-c", kwargs["arguments"]["command"]],
            capture_output=True,
            check=False,
        )
        return {"metadata": {"exit_code": result.returncode}}

    sandbox.execute_tool.side_effect = remote
    try:
        async with sessions() as setup:
            snapshot_id = await MarketplaceSnapshotCache(setup, "tenant", "project").register(
                {"digest": "e" * 64, "files": {}}, root, owner_id=owner
            )
            await setup.commit()
        async with (
            sessions() as caller,
            lease_marketplace_snapshots(caller, "tenant", "project", runtime_root=root),
        ):
            pass  # Simulate API connection loss: DB lease is gone; remote Hook is still alive.
        async with sessions() as cleanup:
            cache = MarketplaceSnapshotCache(cleanup, "tenant", "project", sandbox)
            with pytest.raises(ValueError, match="retained"):
                await cache.cleanup("after-api-loss")
            await cleanup.commit()
            retained = await cleanup.get(MarketplaceRecordV3, snapshot_id)
            assert retained.payload["cleanup_error"] == "snapshot_cleanup_deferred"
            assert retained.payload["cleanup_attempts"] == 1
        assert json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "exec",
                    container,
                    "python3",
                    "-c",
                    f"import json,pathlib; print(json.dumps(pathlib.Path({root!r}).exists()))",
                ],
                text=True,
            )
        )
        subprocess.run(
            [
                "docker",
                "exec",
                container,
                "python3",
                "-c",
                f"import os,signal; os.kill({child_pid},signal.SIGTERM)",
            ],
            check=True,
            capture_output=True,
        )
        child_pid = None
        async with sessions() as cleanup:
            assert (
                await MarketplaceSnapshotCache(cleanup, "tenant", "project", sandbox).cleanup(
                    "after-hook-finish"
                )
            )["removed_entries"] == 1
            await cleanup.commit()
    finally:
        if child_pid is not None:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "python3",
                    "-c",
                    f"import os,signal; os.kill({child_pid},signal.SIGTERM)",
                ],
                check=False,
                capture_output=True,
            )
        subprocess.run(
            [
                "docker",
                "exec",
                container,
                "python3",
                "-c",
                f"import pathlib,shutil; p=pathlib.Path({root!r}); shutil.rmtree(p) if p.exists() else None",
            ],
            check=False,
            capture_output=True,
        )
