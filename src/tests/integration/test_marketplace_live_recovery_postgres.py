"""Recover committed ROOT requests and ambiguous receipts on isolated PostgreSQL schemas."""

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.application.services.test_marketplace_live_requested_recovery_v2 import (
    _recovery,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_requested_restart_v2 import (
    _failed_marketplace_request,
    _state,
)

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions


async def _recover_ambiguous(recovery, normal, host, factory, old, failure):
    with pytest.raises(OSError) as caught:
        await recovery.run_once()
    assert caught.value is failure
    pending = host.pending_receipt
    assert pending is not None and pending.accepted
    assert host.current_publication is old
    with pytest.raises(RuntimeV2Error) as blocked:
        await host.acquire()
    assert blocked.value.code == "publication_receipt_pending"
    assert (await _state(factory))[2] == (2, 2)
    generation = host.manager.current
    assert await normal.run_once() is True
    assert host.manager.current is generation
    assert host.current_publication is pending


@pytest.mark.parametrize("ambiguous_receipt", [False, True])
async def test_live_postgres_recovery_preserves_request_and_idempotent_receipt(
    root_sessions, monkeypatch, ambiguous_receipt
):
    factory = root_sessions
    app = FastAPI()
    calls, receipt_pids = [], []
    failure = OSError("recovery receipt committed but acknowledgement lost")

    class ReceiptSession(AsyncSession):
        async def commit(self):
            receipt_pids.append(await self.scalar(text("SELECT pg_backend_pid()")))
            await super().commit()
            if ambiguous_receipt:
                raise failure

    receipt_factory = async_sessionmaker(
        factory.kw["bind"], class_=ReceiptSession, expire_on_commit=False
    )
    recoveries = []
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        old = host.current_publication
        original = PlatformPluginRuntimeHostV2.apply

        async def apply(owner, *args, **kwargs):
            calls.append(owner)
            return await original(owner, *args, **kwargs)

        monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
        await _failed_marketplace_request(factory, app, host, OSError("request response lost"))
        saved, _good, counts = await _state(factory)
        assert counts == (2, 1)
        assert calls == [] and host.pending_receipt is None
        recovery = _recovery(app, host, receipt_factory)
        normal = _recovery(app, host, factory)
        recoveries.extend((recovery, normal))
        # Hold A for the entire recovery. Actual receipt commit must occur on another backend.
        async with factory() as held:
            pid_a = await held.scalar(text("SELECT pg_backend_pid()"))
            if ambiguous_receipt:
                await _recover_ambiguous(recovery, normal, host, factory, old, failure)
            else:
                assert await recovery.run_once() is True
            assert len(receipt_pids) == 1 and receipt_pids[0] != pid_a
            latest, good, restored_counts = await _state(factory)
            assert latest == good == saved
            assert restored_counts == (2, 2)
            assert host.current_distribution.to_payload() == saved
            assert host.pending_receipt is None
            assert calls == [host]
            assert await normal.run_once() is False
            assert calls == [host]
            assert (await _state(factory))[2] == (2, 2)
            lease = await host.acquire()
            await lease.release()
    finally:
        for recovery in recoveries:
            await recovery.stop()
        await shutdown_plugin_runtime_v2(app)
