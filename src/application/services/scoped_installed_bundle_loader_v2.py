"""Independent-session installed bundle loading for scoped publication.

This callback verifies installed artifacts, not caller authorization. Each call
owns its database session and bounded HTTP client until verification or failure
has finished. No governance state or open transport is cached across calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient, normalize_registry
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2

from .installed_verified_bundle_loader_v2 import InstalledVerifiedBundleLoaderV2


class ScopedInstalledBundleLoaderV2:
    """Callable verified archive resolver; factories must return a fresh HTTP client."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        production_sources: ProductionBundleSourcesV2,
        trusted_public_keys: tuple[str, ...],
        allowed_registries: frozenset[str],
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._production_sources = production_sources
        self._trusted_public_keys = tuple(trusted_public_keys)
        self._allowed_registries = frozenset(
            normalize_registry(registry) for registry in allowed_registries
        )
        self._http_client_factory = http_client_factory or _create_http_client

    async def __call__(
        self, reference: BundleReferenceV2, *, scope: ScopeV2 = ScopeV2(kind=ScopeKindV2.ROOT)
    ) -> VerifiedBundleArchiveV2:
        # A total deadline also bounds slow streams that never hit an idle timeout.
        async with asyncio.timeout(60):
            async with self._session_factory() as session:
                async with self._http_client_factory() as client:
                    loader = InstalledVerifiedBundleLoaderV2(
                        governance_repository=PlatformPluginGovernanceRepository(session),
                        artifact_client=OciPluginArtifactClient(client),
                        production_sources=self._production_sources,
                        trusted_public_keys=self._trusted_public_keys,
                        allowed_registries=self._allowed_registries,
                        scope=scope,
                    )
                    return await loader.load(reference)


def _create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=0),
        follow_redirects=False,
        trust_env=False,
    )
