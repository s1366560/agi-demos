"""Consistent durable recovery evidence; no desired publication or receipt fabrication."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    DesiredBundleSetV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.protocol import (
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
    parse_snapshot_apply_receipt_v2,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
)

from .models import PlatformPluginV2ApplyStateModel, PlatformPluginV2PublicationModel
from .platform_plugin_ledger_validation_v2 import (
    requested_distribution_v2,
    validate_publication_receipt_v2,
)
from .platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from .platform_plugin_scope_ledger_v2 import ScopeLedgerBindingV2


class PlatformPluginRecoveryV2Error(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ScopedRecoveryStateV2:
    scope: ScopeV2
    latest: PlatformPluginDistributionV2 | None
    last_good: PlatformPluginDistributionV2 | None
    latest_receipt: SnapshotApplyReceiptV2 | None
    source: DesiredBundleSetV2 | None


class PlatformPluginRecoveryRepositoryV2:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def read(self, scope: ScopeV2, data_plane_id: str) -> ScopedRecoveryStateV2:
        if not isinstance(cast(object, data_plane_id), str) or not data_plane_id.strip():
            raise PlatformPluginRecoveryV2Error(
                "recovery_plane_invalid", "data plane id must be non-empty"
            )
        binding = ScopeLedgerBindingV2(scope, PlatformPluginRecoveryV2Error)
        _ = await binding.lock(self._session)
        latest_row = (
            await self._session.scalars(
                select(PlatformPluginV2PublicationModel)
                .where(PlatformPluginV2PublicationModel.scope_key == binding.key)
                .order_by(
                    PlatformPluginV2PublicationModel.requested_version.desc(),
                    PlatformPluginV2PublicationModel.created_at.desc(),
                    PlatformPluginV2PublicationModel.id.desc(),
                )
                .limit(1)
                .execution_options(populate_existing=True)
            )
        ).first()
        latest = None if latest_row is None else _distribution(latest_row, binding)
        state = (
            await self._session.scalars(
                select(PlatformPluginV2ApplyStateModel)
                .where(
                    PlatformPluginV2ApplyStateModel.scope_key == binding.key,
                    PlatformPluginV2ApplyStateModel.data_plane_id == data_plane_id,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if state is None:
            return ScopedRecoveryStateV2(binding.scope, latest, None, None, None)
        binding.require_row(state)
        requested_row = await self._session.get(
            PlatformPluginV2PublicationModel, state.requested_publication_id, populate_existing=True
        )
        if requested_row is None:
            raise PlatformPluginRecoveryV2Error(
                "recovery_requested_missing", "receipt lost requested publication"
            )
        if data_plane_id not in requested_row.required_data_plane_ids:
            raise PlatformPluginRecoveryV2Error(
                "recovery_plane_unregistered",
                "receipt plane is not registered for requested publication",
            )
        requested = _distribution(requested_row, binding)
        last_good = None
        source = None
        if state.applied_publication_id is not None:
            applied_row = await self._session.get(
                PlatformPluginV2PublicationModel,
                state.applied_publication_id,
                populate_existing=True,
            )
            if applied_row is None:
                raise PlatformPluginRecoveryV2Error(
                    "recovery_applied_missing", "receipt lost applied publication"
                )
            if data_plane_id not in applied_row.required_data_plane_ids:
                raise PlatformPluginRecoveryV2Error(
                    "recovery_plane_unregistered",
                    "receipt plane is not registered for applied publication",
                )
            last_good = _distribution(applied_row, binding)
            if (state.applied_version, state.applied_digest) != (
                last_good.envelope.version,
                last_good.snapshot.digest,
            ):
                raise PlatformPluginRecoveryV2Error(
                    "recovery_applied_mismatch", "receipt applied identity differs"
                )
            source = await PlatformPluginPublicationSourceRepositoryV2(self._session).read(
                scope=binding.scope, publication_id=applied_row.id
            )
        elif state.applied_version is not None or state.applied_digest is not None:
            raise PlatformPluginRecoveryV2Error(
                "recovery_applied_mismatch", "receipt applied reference is missing"
            )
        receipt = parse_snapshot_apply_receipt_v2(
            {
                "status": state.status,
                "requested_version": state.requested_version,
                "requested_digest": state.requested_digest,
                "applied_version": state.applied_version,
                "applied_digest": state.applied_digest,
                "error_code": state.error_code,
                "error_message": state.error_message,
            }
        )
        validate_publication_receipt_v2(
            PlatformPluginPublicationV2(
                snapshot=requested.snapshot, envelope=requested.envelope, receipt=receipt
            )
        )
        if (
            receipt.status is ApplyStatusV2.ACK
            and state.applied_publication_id != state.requested_publication_id
        ):
            raise PlatformPluginRecoveryV2Error(
                "recovery_ack_reference_mismatch", "ACK must reference its requested publication"
            )
        if latest_row is None:
            raise PlatformPluginRecoveryV2Error(
                "recovery_latest_missing", "receipt exists without latest publication"
            )
        return ScopedRecoveryStateV2(
            binding.scope,
            latest,
            last_good,
            receipt if state.requested_publication_id == latest_row.id else None,
            source,
        )


def _distribution(
    row: PlatformPluginV2PublicationModel, binding: ScopeLedgerBindingV2
) -> PlatformPluginDistributionV2:
    binding.require_row(row)
    payload = deepcopy(row.distribution)
    if set(payload) != {"descriptor", "snapshot", "envelope"}:
        raise PlatformPluginRecoveryV2Error(
            "recovery_distribution_invalid", "stored distribution fields differ"
        )
    result = requested_distribution_v2(
        parse_profile_snapshot_v2(payload["snapshot"]),
        parse_control_envelope_v2(payload["envelope"]),
    )
    descriptor = payload["descriptor"]
    if not isinstance(descriptor, dict):
        raise PlatformPluginRecoveryV2Error(
            "recovery_distribution_invalid", "descriptor must be an object"
        )
    if PluginGenerationDescriptorV2.from_payload(
        cast(dict[str, Any], descriptor)
    ) != result.descriptor or (
        row.profile_id,
        row.generation,
        row.snapshot_digest,
        row.requested_version,
        row.nonce,
        row.type_url,
    ) != (
        result.snapshot.profile_id,
        result.snapshot.generation,
        result.snapshot.digest,
        result.envelope.version,
        result.envelope.nonce,
        result.envelope.type_url,
    ):
        raise PlatformPluginRecoveryV2Error(
            "recovery_distribution_mismatch", "stored publication identity differs"
        )
    return result
