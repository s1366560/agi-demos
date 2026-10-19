"""Independent-session installed bundle loading for scoped publication.

This callback verifies installed artifacts, not caller authorization. Each call
owns its database session and bounded HTTP client until verification or failure
has finished. No governance state or open transport is cached across calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient, normalize_registry
from src.infrastructure.plugins.v2.bundle_archive import (
    VerifiedBundleArchiveV2,
    parse_bundle_archive_v2,
)
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_BUNDLE_SOURCE_V2,
    ProductionBundleSourcesV2,
)

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
        self._production_archive: VerifiedBundleArchiveV2 | None = None

    async def __call__(
        self, reference: BundleReferenceV2, *, scope: ScopeV2 = ScopeV2(kind=ScopeKindV2.ROOT)
    ) -> VerifiedBundleArchiveV2:
        if reference.source == PRODUCTION_BASE_BUNDLE_SOURCE_V2:
            return self._load_production(reference)
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

    def _load_production(self, reference: BundleReferenceV2) -> VerifiedBundleArchiveV2:
        # The deployment owns these immutable bytes. Third-party bundles always
        # follow the fresh governance/permission checks above, including revocation.
        sources = self._production_sources
        InstalledVerifiedBundleLoaderV2._validate_reference(reference, sources.bundle)
        archive = self._production_archive
        if archive is None:
            archive = parse_bundle_archive_v2(
                sources.bundle_archive,
                source=reference.source,
                approved_permissions=frozenset(
                    permission
                    for manifest in sources.bundle.manifests
                    for permission in manifest.permissions
                ),
                require_signature=False,
                require_provenance=True,
            )
            InstalledVerifiedBundleLoaderV2._validate_reference(reference, archive.manifest)
            self._production_archive = archive
        InstalledVerifiedBundleLoaderV2._validate_reference(reference, archive.manifest)
        # Artifact bytes and their mapping are immutable; manifest configs are not.
        result = replace(archive, manifest=deepcopy(archive.manifest))
        object.__setattr__(result, "_signed_verification", archive._signed_verification)
        return result


def _create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=0),
        follow_redirects=False,
        trust_env=False,
    )
