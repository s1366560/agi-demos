"""Retain a superseded real outcome without forging a current data-plane receipt."""

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeV2
from src.infrastructure.plugins.v2.protocol import (
    parse_snapshot_apply_receipt_v2,
    snapshot_apply_receipt_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
)

from .models import PlatformPluginV2PublicationModel
from .platform_plugin_desired_bundle_repository_v2 import PlatformPluginDesiredBundleSetRepositoryV2
from .platform_plugin_ledger_validation_v2 import (
    requested_distribution_v2,
    validate_publication_receipt_v2,
)
from .platform_plugin_outcome_supersession_model_v2 import PlatformPluginV2OutcomeSupersessionModel
from .platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from .platform_plugin_scope_ledger_v2 import ScopeLedgerBindingV2


class PlatformPluginOutcomeSupersessionV2Error(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PlatformPluginOutcomeSupersessionRepositoryV2:
    """The caller owns the transaction and must commit before replacing local state."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def _requested(
        self, binding: ScopeLedgerBindingV2, distribution: PlatformPluginDistributionV2
    ) -> PlatformPluginV2PublicationModel:
        row = (
            await self._session.scalars(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.scope_key == binding.key,
                    PlatformPluginV2PublicationModel.nonce == distribution.envelope.nonce,
                )
            )
        ).one_or_none()
        if row is None:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_publication_missing", "supersession request is unavailable"
            )
        binding.require_row(row)
        expected = requested_distribution_v2(distribution.snapshot, distribution.envelope)
        if (
            distribution != expected
            or row.distribution != expected.to_payload()
            or (
                row.profile_id,
                row.generation,
                row.snapshot_digest,
                row.requested_version,
                row.type_url,
            )
            != (
                expected.snapshot.profile_id,
                expected.snapshot.generation,
                expected.snapshot.digest,
                expected.envelope.version,
                expected.envelope.type_url,
            )
        ):
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_distribution_mismatch", "supersession request identity differs"
            )
        return row

    async def record(
        self,
        *,
        scope: ScopeV2,
        data_plane_id: str,
        outcome: PlatformPluginPublicationV2,
        replacement: PlatformPluginDistributionV2,
    ) -> PlatformPluginV2OutcomeSupersessionModel:
        binding = ScopeLedgerBindingV2(scope, PlatformPluginOutcomeSupersessionV2Error)
        _ = await binding.lock(self._session)
        previous = await self._requested(
            binding, requested_distribution_v2(outcome.snapshot, outcome.envelope)
        )
        candidate = await self._requested(binding, replacement)
        if (
            not data_plane_id.strip()
            or data_plane_id not in previous.required_data_plane_ids
            or data_plane_id not in candidate.required_data_plane_ids
        ):
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_plane_unregistered", "supersession data plane is not registered"
            )
        if candidate.requested_version <= previous.requested_version:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_not_newer", "replacement must have a newer requested version"
            )
        latest_id = await self._session.scalar(
            select(PlatformPluginV2PublicationModel.id)
            .where(PlatformPluginV2PublicationModel.scope_key == binding.key)
            .order_by(
                PlatformPluginV2PublicationModel.requested_version.desc(),
                PlatformPluginV2PublicationModel.created_at.desc(),
                PlatformPluginV2PublicationModel.id.desc(),
            )
            .limit(1)
        )
        if latest_id != candidate.id:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_replacement_stale", "replacement is no longer the latest request"
            )
        source = await PlatformPluginPublicationSourceRepositoryV2(self._session).read(
            scope=binding.scope, publication_id=candidate.id
        )
        if source is None:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_source_missing", "replacement has no source binding"
            )
        desired = await PlatformPluginDesiredBundleSetRepositoryV2(
            self._session
        ).current_desired_set(binding.scope)
        if desired is None or desired.desired_set != source:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_source_changed", "replacement desired source changed"
            )
        try:
            receipt = parse_snapshot_apply_receipt_v2(
                snapshot_apply_receipt_v2_to_payload(outcome.receipt)
            )
            validate_publication_receipt_v2(replace(outcome, receipt=receipt))
            if (receipt.applied_version is None) != (receipt.applied_digest is None):
                raise ValueError("applied identity must be complete")
        except ValueError as error:
            raise PlatformPluginOutcomeSupersessionV2Error(
                "supersession_receipt_invalid", "supersession outcome receipt is invalid"
            ) from error
        if receipt.applied_version is not None:
            applied = await self._session.scalar(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.scope_key == binding.key,
                    PlatformPluginV2PublicationModel.requested_version == receipt.applied_version,
                    PlatformPluginV2PublicationModel.snapshot_digest == receipt.applied_digest,
                )
            )
            if applied is None:
                raise PlatformPluginOutcomeSupersessionV2Error(
                    "supersession_receipt_invalid", "applied outcome identity is unavailable"
                )
        payload = snapshot_apply_receipt_v2_to_payload(receipt)
        identity = (binding.key, data_plane_id, previous.id, candidate.id)
        existing = await self._session.get(PlatformPluginV2OutcomeSupersessionModel, identity)
        if existing is not None:
            binding.require_row(existing)
            if existing.receipt_payload != payload:
                raise PlatformPluginOutcomeSupersessionV2Error(
                    "supersession_conflict", "supersession outcome is immutable"
                )
            return existing
        record = PlatformPluginV2OutcomeSupersessionModel(
            **binding.fields,
            data_plane_id=data_plane_id,
            outcome_publication_id=previous.id,
            replacement_publication_id=candidate.id,
            receipt_payload=payload,
        )
        self._session.add(record)
        await self._session.flush()
        return record
