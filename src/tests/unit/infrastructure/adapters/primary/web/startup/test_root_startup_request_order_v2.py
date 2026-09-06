"""ROOT startup persists requested lineage before apply and gates installation on receipts."""

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


async def _counts(session):
    return tuple(
        [
            await session.scalar(select(func.count()).select_from(model))
            for model in (
                PlatformPluginV2PublicationModel,
                PlatformPluginV2PublicationSourceModel,
                PlatformPluginV2ApplyStateEventModel,
            )
        ]
    )


def _observe_hosts(monkeypatch):
    applied, closed = [], []
    original_apply = PlatformPluginRuntimeHostV2.apply
    original_close = PlatformPluginRuntimeHostV2.close

    async def apply(host, *args, **kwargs):
        applied.append(host)
        return await original_apply(host, *args, **kwargs)

    async def close(host):
        try:
            await original_close(host)
        finally:
            closed.append(host)

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "close", close)
    return applied, closed


async def test_route_staging_observes_committed_request_and_source_without_receipt(
    db_session, monkeypatch
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    original_apply = PlatformPluginRuntimeHostV2.apply
    seen = []

    async def apply(host, snapshot, envelope, **kwargs):
        stage = kwargs["publication_stager"]

        async def observe(generation):
            async with factory() as other:
                assert await _counts(other) == (1, 1, 0)
                row = (await other.scalars(select(PlatformPluginV2PublicationModel))).one()
                assert row.nonce == envelope.nonce
                source = await PlatformPluginPublicationSourceRepositoryV2(other).read(
                    scope=ROOT, publication_id=row.id
                )
                assert source is not None
                seen.append(row.id)
            return await stage(generation)

        return await original_apply(
            host, snapshot, envelope, **{**kwargs, "publication_stager": observe}
        )

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert app.state.platform_plugin_runtime_v2 is host
        assert len(seen) == 1
        async with factory() as session:
            assert await _counts(session) == (1, 1, 1)
    finally:
        await shutdown_plugin_runtime_v2(app)


@pytest.mark.parametrize("after", [False, True])
async def test_requested_commit_failure_never_applies_or_installs(db_session, monkeypatch, after):
    fault = OSError("requested commit fault")
    injected = []

    class FaultSession(AsyncSession):
        async def commit(self):
            if not injected and await _counts(self) == (1, 1, 0):
                injected.append(True)
                if after:
                    await super().commit()
                raise fault
            await super().commit()

    factory = async_sessionmaker(db_session.bind, class_=FaultSession, expire_on_commit=False)
    applied, closed = _observe_hosts(monkeypatch)
    app = FastAPI()
    with pytest.raises(OSError) as caught:
        await initialize_plugin_runtime_v2(app, session_factory=factory)
    assert caught.value is fault
    assert injected == [True]
    assert applied == []
    assert len(closed) == 1 and closed[0].manager.current is None
    assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    async with factory() as session:
        assert await _counts(session) == ((1, 1, 0) if after else (0, 0, 0))


@pytest.mark.parametrize("after", [False, True])
async def test_receipt_commit_failure_closes_applied_host_without_installation(
    db_session, monkeypatch, after
):
    fault = OSError("receipt commit fault")
    injected = []

    class FaultSession(AsyncSession):
        async def commit(self):
            if not injected and (await _counts(self))[2] == 1:
                injected.append(True)
                if after:
                    await super().commit()
                raise fault
            await super().commit()

    factory = async_sessionmaker(db_session.bind, class_=FaultSession, expire_on_commit=False)
    applied, closed = _observe_hosts(monkeypatch)
    app = FastAPI()
    with pytest.raises(OSError) as caught:
        await initialize_plugin_runtime_v2(app, session_factory=factory)
    assert caught.value is fault
    assert len(applied) == 1 and closed == applied
    assert applied[0].manager.current is None
    assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    async with factory() as session:
        assert await _counts(session) == (1, 1, 1 if after else 0)


async def test_superseding_request_during_route_stage_rejects_stale_receipt_and_install(
    db_session, monkeypatch
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    original_apply = PlatformPluginRuntimeHostV2.apply
    hosts = []

    async def apply(host, snapshot, envelope, **kwargs):
        hosts.append(host)
        stage = kwargs["publication_stager"]

        async def supersede(generation):
            async with factory() as other:
                repository = PlatformPluginRepositoryV2(other)
                version = await repository.allocate_publication_version()
                assert version > envelope.version
                await repository.record_requested_distribution(
                    snapshot, control_envelope_v2(snapshot, version=version)
                )
                await other.commit()
            return await stage(generation)

        return await original_apply(
            host, snapshot, envelope, **{**kwargs, "publication_stager": supersede}
        )

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    with pytest.raises(PlatformPluginLedgerV2Error) as caught:
        await initialize_plugin_runtime_v2(app, session_factory=factory)
    assert caught.value.code == "stale_receipt"
    assert len(hosts) == 1 and hosts[0].manager.current is None
    assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    async with factory() as session:
        assert await _counts(session) == (2, 1, 0)


@pytest.mark.parametrize("failure", ["desired-changed", "empty-archives"])
async def test_prepare_rejects_stale_desired_or_incomplete_archives_before_apply(
    db_session, monkeypatch, failure
):
    from dataclasses import replace

    from src.infrastructure.adapters.primary.web.startup import root_profile_startup_v2
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
        PlatformPluginDesiredBundleSetRepositoryV2,
    )
    from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    original = root_profile_startup_v2.prepare_root_startup_request_v2
    changed = []

    async def prepare(**kwargs):
        if failure == "desired-changed":
            # The real archive await and composition have completed; another transaction wins CAS.
            desired = kwargs["desired"]
            newer = replace(desired, revision=desired.revision + 1)
            newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))
            async with factory() as other:
                await PlatformPluginDesiredBundleSetRepositoryV2(other).record_desired_set(
                    scope=ROOT,
                    desired_set=newer,
                    expected_revision=desired.revision,
                    actor_id="concurrent-writer",
                )
                await other.commit()
            changed.append(newer)
        else:
            kwargs["archives"] = ()
        return await original(**kwargs)

    monkeypatch.setattr(root_profile_startup_v2, "prepare_root_startup_request_v2", prepare)
    applied, closed = _observe_hosts(monkeypatch)
    app = FastAPI()
    with pytest.raises(RuntimeV2Error) as caught:
        await initialize_plugin_runtime_v2(app, session_factory=factory)
    assert caught.value.code == (
        "root_desired_changed" if failure == "desired-changed" else "root_bundle_reference_mismatch"
    )
    assert applied == []
    assert len(closed) == 1 and closed[0].manager.current is None
    assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    async with factory() as session:
        assert await _counts(session) == (0, 0, 0)
        if changed:
            actual = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
                ROOT
            )
            assert actual.desired_set == changed[0]
