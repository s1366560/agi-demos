"""Marketplace receipt fences across real PostgreSQL connections and committed transactions."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.marketplace_publication_receipt_v2 import (
    persist_marketplace_receipt_v2,
)
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
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.application.services.test_marketplace_verified_execution_v2 import (
    _NoExternalArtifactClient,
)

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


async def _counts(factory):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    PlatformPluginV2PublicationModel,
                    PlatformPluginV2ApplyStateEventModel,
                )
            ]
        )


async def _observe_stage(
    factory, mutation, case, snapshot, envelope, observations, stage, generation
):
    assert not mutation.in_transaction()
    # Keep the actual mutation session's connection checked out while B reads/writes.
    pid_a = await mutation.scalar(text("SELECT pg_backend_pid()"))
    async with factory() as reader:
        pid_b = await reader.scalar(text("SELECT pg_backend_pid()"))
        assert pid_a != pid_b
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
        desired = await PlatformPluginDesiredBundleSetRepositoryV2(reader).current_desired_set(ROOT)
        assert source == desired.desired_set
        assert (
            await reader.scalar(
                select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
            )
            == 1
        )
        if case == "superseded":
            repository = PlatformPluginRepositoryV2(reader)
            version = await repository.allocate_publication_version()
            assert version > envelope.version
            await repository.record_requested_distribution(
                snapshot, control_envelope_v2(snapshot, version=version)
            )
            await reader.commit()
        observations.append((pid_a, pid_b, envelope.nonce))
    return await stage(generation)


async def _retry_ambiguous(app, coordinator, host, factory, policy, observations, committed):
    pending = host.pending_receipt
    generation = host.manager.current
    routes = app.state.platform_plugin_route_registry_v2.current
    result = await coordinator.retry_pending_receipt(
        lambda publication: persist_marketplace_receipt_v2(factory, publication, policy=policy)
    )
    assert result.plugin_publication is pending
    assert host.pending_receipt is None
    assert host.manager.current is generation
    assert app.state.platform_plugin_route_registry_v2.current is routes
    assert len(observations) == 1
    assert await _counts(factory) == (2, 2)
    committed.assert_called_once()


@pytest.mark.parametrize("case", ["committed", "ambiguous-receipt", "superseded"])
async def test_marketplace_requested_and_receipt_fences_across_postgres_backends(
    root_sessions, monkeypatch, case
):
    factory = root_sessions
    app = FastAPI()
    observations, receipt_pids = [], []
    failure = OSError("receipt committed but acknowledgement lost")

    class ReceiptSession(AsyncSession):
        async def commit(self):
            receipt_pids.append(await self.scalar(text("SELECT pg_backend_pid()")))
            await super().commit()
            if case == "ambiguous-receipt":
                raise failure

    receipt_factory = async_sessionmaker(
        factory.kw["bind"], class_=ReceiptSession, expire_on_commit=False
    )
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        old_publication = host.current_publication
        coordinator = app.state.platform_plugin_http_route_publication_v2
        policy = app.state.platform_plugin_publication_policy_v2
        original = PlatformPluginRuntimeHostV2.apply
        committed = MagicMock()

        async def apply(owner, snapshot, envelope, **kwargs):
            stage = kwargs["publication_stager"]

            async def observe(generation):
                return await _observe_stage(
                    factory, mutation, case, snapshot, envelope, observations, stage, generation
                )

            return await original(
                owner, snapshot, envelope, **{**kwargs, "publication_stager": observe}
            )

        monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
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
                route_coordinator=coordinator,
                publication_policy=policy,
                on_route_commit=committed,
            )
            if case == "committed":
                result = await service.publish_current()
                assert result.publication.accepted
                assert host.pending_receipt is None
                committed.assert_called_once()
            else:
                error = OSError if case == "ambiguous-receipt" else PlatformPluginLedgerV2Error
                with pytest.raises(error) as caught:
                    await service.publish_current()
                if case == "ambiguous-receipt":
                    assert caught.value is failure
                else:
                    assert caught.value.code == "stale_receipt"
                assert host.pending_receipt.accepted  # Actual local ACK; never fabricate a NACK.
                assert host.current_publication is old_publication
                committed.assert_not_called()
                with pytest.raises(RuntimeV2Error) as blocked:
                    await host.acquire()
                assert blocked.value.code == "publication_receipt_pending"
            assert len(observations) == 1
            assert len(receipt_pids) == (0 if case == "superseded" else 1)
            assert all(pid != observations[0][0] for pid in receipt_pids)
            assert await _counts(factory) == ((3, 1) if case == "superseded" else (2, 2))
            if case == "ambiguous-receipt":
                await _retry_ambiguous(
                    app, coordinator, host, factory, policy, observations, committed
                )
            if case != "superseded":
                lease = await host.acquire()
                await lease.release()
    finally:
        await shutdown_plugin_runtime_v2(app)
