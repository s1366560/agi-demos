"""Marketplace ROOT publications bind verified bytes to the actual route-owning Loader."""

from dataclasses import replace
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.plugin_marketplace_publication_service_v2 import (
    PluginMarketplacePublicationServiceV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2_to_payload

pytestmark = pytest.mark.unit


class _NoExternalArtifactClient:
    async def fetch_bundle(self, *_args, **_kwargs):
        raise AssertionError("production builtin archive must not use external fetch")


async def test_marketplace_archive_tamper_nacks_without_route_commit_and_next_candidate_recovers(
    db_session, monkeypatch
):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        routes = app.state.platform_plugin_route_registry_v2
        committed = MagicMock()
        async with factory() as session:
            repository = PlatformPluginRepositoryV2(session)
            service = PluginMarketplacePublicationServiceV2(
                desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(session),
                source_repository=PlatformPluginProfileSourceRepositoryV2(session),
                governance_repository=PlatformPluginGovernanceRepository(session),
                publication_repository=repository,
                artifact_client=_NoExternalArtifactClient(),
                production_sources=production_bundle_sources_v2(),
                trusted_public_keys=(),
                allowed_registries=frozenset(),
                host=host,
                route_coordinator=app.state.platform_plugin_http_route_publication_v2,
                publication_policy=app.state.platform_plugin_publication_policy_v2,
                on_route_commit=committed,
            )
            initial = await service.publish_current()
            await session.commit()
            assert initial.publication.accepted
            committed.assert_called_once()
            assert routes.current.descriptor == host.manager.current.descriptor
            good_routes = routes.current
            good_generation = host.manager.current
            good_publication = host.current_publication
            saved = await repository.last_good_distribution("python-api-v2")
            assert saved["envelope"] == control_envelope_v2_to_payload(initial.publication.envelope)
            load = service._bundle_loader.load

            async def corrupt_after_trust_checks(reference):
                archive = await load(reference)
                # Preserve the verified manifest exactly; only execution bytes are corrupted.
                return replace(
                    archive,
                    artifacts=MappingProxyType(
                        {
                            key: value + b"\ncorrupt-after-verification"
                            for key, value in archive.artifacts.items()
                        }
                    ),
                )

            monkeypatch.setattr(service._bundle_loader, "load", corrupt_after_trust_checks)
            committed.reset_mock()
            rejected = await service.publish_current()
            await session.commit()
            assert not rejected.publication.accepted
            assert rejected.publication.receipt.error_code == "staging_failed"
            assert host.manager.current is good_generation
            assert host.current_publication == good_publication
            assert routes.current is good_routes
            committed.assert_not_called()
            assert await repository.last_good_distribution("python-api-v2") == saved
            failed_row = (
                await session.scalars(
                    select(PlatformPluginV2PublicationModel).where(
                        PlatformPluginV2PublicationModel.nonce
                        == rejected.publication.envelope.nonce
                    )
                )
            ).one()
            assert failed_row.snapshot_digest == rejected.publication.snapshot.digest
            monkeypatch.setattr(service._bundle_loader, "load", load)
            recovered = await service.publish_current()
            await session.commit()
            assert recovered.publication.accepted
            committed.assert_called_once()
            assert host.manager.current is not good_generation
            assert routes.current is not good_routes
            assert routes.current.descriptor == host.manager.current.descriptor
            assert (await repository.last_good_distribution("python-api-v2"))[
                "envelope"
            ] == control_envelope_v2_to_payload(recovered.publication.envelope)
    finally:
        await shutdown_plugin_runtime_v2(app)
