"""Marketplace mutation commit precedes real route staging and durable admission."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.mark.parametrize("receipt_fails", [None, "before", "after"])
async def test_requested_source_commit_is_visible_before_stage_and_receipt_gates_admission(
    db_session, monkeypatch, receipt_fails
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    failure = OSError("receipt commit fault")
    observed, receipt_sessions = [], []

    class ReceiptSession(AsyncSession):
        async def commit(self):
            receipt_sessions.append(self)
            if receipt_fails == "after":
                await super().commit()
            if receipt_fails:
                raise failure
            await super().commit()

    receipt_factory = async_sessionmaker(
        db_session.bind, class_=ReceiptSession, expire_on_commit=False
    )
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        old = host.current_publication
        original = PlatformPluginRuntimeHostV2.apply

        async def apply(owner, snapshot, envelope, **kwargs):
            stage = kwargs["publication_stager"]

            async def observe(generation):
                assert not mutation.in_transaction()
                async with factory() as reader:
                    row = (
                        await reader.scalars(
                            select(PlatformPluginV2PublicationModel).where(
                                PlatformPluginV2PublicationModel.nonce == envelope.nonce
                            )
                        )
                    ).one()
                    source = await PlatformPluginPublicationSourceRepositoryV2(reader).read(
                        scope=ROOT, publication_id=row.id
                    )
                    desired = await PlatformPluginDesiredBundleSetRepositoryV2(
                        reader
                    ).current_desired_set(ROOT)
                    assert source == desired.desired_set
                    assert (
                        await reader.scalar(
                            select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
                        )
                        == 1
                    )  # Only the preceding startup ACK exists.
                    observed.append(row.nonce)
                return await stage(generation)

            return await original(
                owner, snapshot, envelope, **{**kwargs, "publication_stager": observe}
            )

        monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
        committed = MagicMock()
        async with factory() as mutation:
            service = PluginMarketplacePublicationServiceV2(
                mutation_session=mutation,
                receipt_session_factory=receipt_factory,
                desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(mutation),
                source_repository=PlatformPluginProfileSourceRepositoryV2(mutation),
                governance_repository=PlatformPluginGovernanceRepository(mutation),
                publication_repository=PlatformPluginRepositoryV2(mutation),
                artifact_client=_NoExternalArtifactClient(),
                production_sources=production_bundle_sources_v2(),
                trusted_public_keys=(),
                allowed_registries=frozenset(),
                host=host,
                route_coordinator=app.state.platform_plugin_http_route_publication_v2,
                publication_policy=app.state.platform_plugin_publication_policy_v2,
                on_route_commit=committed,
            )
            if receipt_fails:
                with pytest.raises(OSError) as caught:
                    await service.publish_current()
                assert caught.value is failure
                assert host.pending_receipt.accepted
                assert host.current_publication is old
                committed.assert_not_called()
                with pytest.raises(RuntimeV2Error) as blocked:
                    await host.acquire()
                assert blocked.value.code == "publication_receipt_pending"
            else:
                result = await service.publish_current()
                assert result.publication.accepted
                assert host.current_publication is result.publication
                committed.assert_called_once()
                lease = await host.acquire()
                await lease.release()
            assert len(observed) == 1
            assert len(receipt_sessions) == 1 and receipt_sessions[0] is not mutation
        async with factory() as reader:
            assert await reader.scalar(
                select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
            ) == (1 if receipt_fails == "before" else 2)
            assert (
                await reader.scalar(
                    select(func.count()).select_from(PlatformPluginV2PublicationModel)
                )
                == 2
            )
    finally:
        await shutdown_plugin_runtime_v2(app)


@pytest.mark.parametrize("after", [False, True])
async def test_requested_commit_failure_never_applies_marketplace_candidate(
    db_session, monkeypatch, after
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    failure = OSError("requested commit fault")
    calls = []

    class MutationSession(AsyncSession):
        async def commit(self):
            if after:
                await super().commit()
            raise failure

    mutation_factory = async_sessionmaker(
        db_session.bind, class_=MutationSession, expire_on_commit=False
    )
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        old = host.current_publication
        original = PlatformPluginRuntimeHostV2.apply

        async def apply(owner, *args, **kwargs):
            calls.append(owner)
            return await original(owner, *args, **kwargs)

        monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
        async with mutation_factory() as mutation:
            service = PluginMarketplacePublicationServiceV2(
                mutation_session=mutation,
                receipt_session_factory=factory,
                desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(mutation),
                source_repository=PlatformPluginProfileSourceRepositoryV2(mutation),
                governance_repository=PlatformPluginGovernanceRepository(mutation),
                publication_repository=PlatformPluginRepositoryV2(mutation),
                artifact_client=_NoExternalArtifactClient(),
                production_sources=production_bundle_sources_v2(),
                trusted_public_keys=(),
                allowed_registries=frozenset(),
                host=host,
                route_coordinator=app.state.platform_plugin_http_route_publication_v2,
                publication_policy=app.state.platform_plugin_publication_policy_v2,
            )
            with pytest.raises(OSError) as caught:
                await service.publish_current()
            assert caught.value is failure
        assert calls == []
        assert host.current_publication is old
        assert host.pending_receipt is None
        lease = await host.acquire()
        await lease.release()
        async with factory() as reader:
            assert await reader.scalar(
                select(func.count()).select_from(PlatformPluginV2PublicationModel)
            ) == (2 if after else 1)
            assert (
                await reader.scalar(
                    select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
                )
                == 1
            )
    finally:
        await shutdown_plugin_runtime_v2(app)
