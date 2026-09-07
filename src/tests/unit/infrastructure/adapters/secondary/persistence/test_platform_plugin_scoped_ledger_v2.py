"""Scope-private publication/receipt behavior using the real SQL ledger."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ScopeHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_repository_v2 import (
    _publication,
)

pytestmark = pytest.mark.unit
_PLANE = "python-api-v2"


def _scope(tenant="a", project="p", session="s"):
    return ScopeV2(
        kind=ScopeKindV2.SESSION, tenant_id=tenant, project_id=project, session_id=session
    )


def _nonce(publication, nonce):
    return replace(publication, envelope=replace(publication.envelope, nonce=nonce))


async def test_scoped_ledger_isolates_full_identity_and_default_root(db_session):
    publication, _ = await _publication(generation=1, version=1)
    scopes = (
        ScopeV2(kind=ScopeKindV2.ROOT),
        _scope(),
        _scope("b"),
        _scope(project="q"),
        _scope(session="t"),
    )
    rows = []
    for index, scope in enumerate(scopes):
        repository = PlatformPluginRepositoryV2(db_session, scope=scope)
        value = _nonce(publication, f"scope-{index}")
        recorded = await repository.record_publication_and_receipt(value, data_plane_id=_PLANE)
        rows.append(recorded)
        # Identical retry is state/event idempotent within this scope.
        await repository.record_data_plane_receipt(
            data_plane_id=_PLANE, nonce=value.envelope.nonce, receipt=value.receipt
        )
        assert (await repository.last_good_distribution(_PLANE))["envelope"][
            "nonce"
        ] == f"scope-{index}"
    assert len({row.apply_state.id for row in rows}) == 5
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
        )
        == 5
    )
    root = PlatformPluginRepositoryV2(db_session)
    assert (await root.latest_requested_distribution())["envelope"]["nonce"] == "scope-0"
    assert (await root.latest_publication_readiness()).nonce == "scope-0"
    a = PlatformPluginRepositoryV2(db_session, scope=scopes[1])
    replay = await a.republish_last_globally_ready(nonce="a-replay")
    assert replay.requested_version == 2
    assert replay.republished_from_id == rows[1].publication.id
    assert (await root.latest_requested_distribution())["envelope"]["nonce"] == "scope-0"
    b = PlatformPluginRepositoryV2(db_session, scope=scopes[2])
    assert (await b.latest_publication_readiness()).status.value == "ready"


async def test_scoped_ledger_rejects_foreign_nonce_and_publication(db_session):
    publication, _ = await _publication(generation=1, version=1)
    a = PlatformPluginRepositoryV2(db_session, scope=_scope())
    b = PlatformPluginRepositoryV2(db_session, scope=_scope("b"))
    row = await a.record_publication_and_receipt(publication, data_plane_id=_PLANE)
    with pytest.raises(PlatformPluginLedgerV2Error, match="another scope"):
        await b.record_publication(publication)
    with pytest.raises(PlatformPluginLedgerV2Error) as receipt_error:
        await b.record_data_plane_receipt(
            data_plane_id=_PLANE, nonce=publication.envelope.nonce, receipt=publication.receipt
        )
    assert receipt_error.value.code == "publication_not_found"
    with pytest.raises(PlatformPluginLedgerV2Error):
        await b.publication_readiness(publication.envelope.nonce)
    with pytest.raises(PlatformPluginLedgerV2Error, match="another scope"):
        await b._record_receipt(row.publication, publication.receipt, data_plane_id=_PLANE)
    assert await b.latest_requested_distribution() is None
    assert await b.last_good_distribution(_PLANE) is None


async def test_scope_versions_rollback_and_same_version_new_nonce_remain_legal(db_session):
    a = PlatformPluginRepositoryV2(db_session, scope=_scope())
    assert await a.allocate_publication_version() == 1
    await db_session.rollback()
    assert await a.allocate_publication_version() == 1
    assert await a.allocate_publication_version() == 2
    b = PlatformPluginRepositoryV2(db_session, scope=_scope("b"))
    assert await b.allocate_publication_version() == 1
    publication, _ = await _publication(generation=1, version=8)
    first = await a.record_publication(publication)
    second = await a.record_publication(_nonce(publication, "same-version-new-nonce"))
    assert first.requested_version == second.requested_version == 8
    assert first.id != second.id
    await a.record_publication(_nonce(publication, "same-version-new-nonce"))
    assert await a.allocate_publication_version() == 9
    assert await b.allocate_publication_version() == 2
    assert (
        await db_session.scalar(select(func.count()).select_from(PlatformPluginV2ScopeHeadModel))
        == 2
    )


async def test_scope_supersede_and_deadline_do_not_modify_other_scope(db_session):
    publication, _ = await _publication(generation=1, version=1)
    a = PlatformPluginRepositoryV2(db_session, scope=_scope())
    b = PlatformPluginRepositoryV2(db_session, scope=_scope("b"))
    now = datetime.now(UTC)
    old_a = await a.record_publication(_nonce(publication, "a-before"), now=now)
    old_b = await b.record_publication(_nonce(publication, "b-before"), now=now)
    await a.record_publication(_nonce(publication, "a-after"), now=now + timedelta(seconds=1))
    assert old_a.status == "degraded"
    assert old_b.status == "reconciling"
    await a.reconcile_publication_deadlines(now=now + timedelta(days=1))
    assert old_b.status == "reconciling"
