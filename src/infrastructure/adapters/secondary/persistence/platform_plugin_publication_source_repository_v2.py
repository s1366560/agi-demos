"""Immutable publication lineage; stored references never replace archive trust checks."""

from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.protocol import (
    desired_bundle_set_v2_to_payload,
    parse_desired_bundle_set_v2,
)


class PlatformPluginPublicationSourceV2Error(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PlatformPluginPublicationSourceRepositoryV2:
    """The caller commits the publication and its lineage in one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def record(
        self, *, scope: ScopeV2, publication_id: str, desired_set: DesiredBundleSetV2
    ) -> DesiredBundleSetV2:
        binding = ScopeLedgerBindingV2(scope, PlatformPluginPublicationSourceV2Error)
        parsed = parse_desired_bundle_set_v2(
            deepcopy(desired_bundle_set_v2_to_payload(desired_set))
        )
        _ = await binding.lock(self._session)
        publication = await self._session.get(PlatformPluginV2PublicationModel, publication_id)
        if publication is None:
            raise PlatformPluginPublicationSourceV2Error(
                "publication_source_parent_missing",
                "source binding requires a persisted publication",
            )
        binding.require_row(publication)
        if publication.generation != parsed.revision:
            raise PlatformPluginPublicationSourceV2Error(
                "publication_source_revision_mismatch", "publication differs from desired revision"
            )
        payload = desired_bundle_set_v2_to_payload(parsed)
        existing = await self._session.get(PlatformPluginV2PublicationSourceModel, publication_id)
        if existing is not None:
            binding.require_row(existing)
            if existing.payload != payload:
                raise PlatformPluginPublicationSourceV2Error(
                    "publication_source_conflict", "publication source binding is immutable"
                )
            return parsed
        self._session.add(
            PlatformPluginV2PublicationSourceModel(
                publication_id=publication_id,
                **binding.fields,
                payload=payload,
            )
        )
        await self._session.flush()
        return parsed

    async def read(self, *, scope: ScopeV2, publication_id: str) -> DesiredBundleSetV2 | None:
        binding = ScopeLedgerBindingV2(scope, PlatformPluginPublicationSourceV2Error)
        row = await self._session.get(PlatformPluginV2PublicationSourceModel, publication_id)
        if row is None:
            return None
        binding.require_row(row)
        parsed = parse_desired_bundle_set_v2(deepcopy(row.payload))
        publication = await self._session.get(PlatformPluginV2PublicationModel, publication_id)
        if publication is None:
            raise PlatformPluginPublicationSourceV2Error(
                "publication_source_parent_missing", "source binding lost its publication"
            )
        binding.require_row(publication)
        if publication.generation != parsed.revision:
            raise PlatformPluginPublicationSourceV2Error(
                "publication_source_revision_mismatch", "stored source differs from publication"
            )
        return parsed
