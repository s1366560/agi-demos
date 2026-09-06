"""Journal real unreceipted Host outcomes on independently migrated PostgreSQL schemas."""

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_outcome_supersession_model_v2 import (
    PlatformPluginV2OutcomeSupersessionModel,
)
from src.infrastructure.plugins.v2.protocol import snapshot_apply_receipt_v2_to_payload
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_outcome_supersession_v2 import (
    _authority_state,
    _next,
    _record,
    _request,
)

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.mark.parametrize("accepted", [True, False], ids=["ACK", "NACK"])
async def test_real_pending_outcome_journal_is_idempotent_and_preserves_authority(
    root_sessions, accepted
):
    factory = root_sessions
    app = FastAPI()
    lease = None
    failure = OSError("receipt storage unavailable")
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        lease = await host.acquire()
        old = host.current_publication
        async with factory() as session:
            desired = (
                await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(ROOT)
            ).desired_set
        candidate = await _request(
            factory, ROOT, _next(old.snapshot, old.snapshot.generation + 1), desired
        )

        async def fail(_publication):
            raise failure

        with pytest.raises(OSError) as caught:
            await app.state.platform_plugin_http_route_publication_v2.publish_snapshot(
                candidate.snapshot,
                candidate.envelope,
                verified_archives=None if accepted else (),
                receipt_persister=fail,
            )
        assert caught.value is failure
        outcome = host.pending_receipt
        assert outcome is not None and outcome.accepted is accepted
        assert host.current_publication is old
        replacement = await _request(
            factory,
            ROOT,
            _next(candidate.snapshot, candidate.snapshot.generation + 1),
            desired,
        )
        before = await _authority_state(factory)
        first = await _record(factory, ROOT, outcome, replacement)
        second = await _record(factory, ROOT, outcome, replacement)
        assert first.receipt_payload == snapshot_apply_receipt_v2_to_payload(outcome.receipt)
        assert second.receipt_payload == first.receipt_payload
        assert second.created_at == first.created_at
        assert await _authority_state(factory) == before
        assert host.pending_receipt is outcome
        assert host.current_publication is old
        with pytest.raises(RuntimeV2Error) as blocked:
            await host.acquire()
        assert blocked.value.code == "publication_receipt_pending"
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
                )
                == 1
            )
    finally:
        if lease is not None:
            await lease.release()
        await shutdown_plugin_runtime_v2(app)
