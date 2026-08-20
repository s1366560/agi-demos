"""Durable protocol-v2 publication and data-plane receipt ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ApplyStatusV2, SnapshotApplyReceiptV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
)

PYTHON_API_DATA_PLANE_ID_V2 = "python-api-v2"


@dataclass(frozen=True, kw_only=True)
class PlatformPluginLedgerRecordV2:
    """One requested publication and its latest data-plane state."""

    publication: PlatformPluginV2PublicationModel
    apply_state: PlatformPluginV2ApplyStateModel


class PlatformPluginRepositoryV2:
    """Persist v2 distributions separately from the legacy control-plane tables."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def record_publication(
        self,
        publication: PlatformPluginPublicationV2,
    ) -> PlatformPluginV2PublicationModel:
        """Append one complete requested distribution, deduping only its nonce."""
        _validate_receipt(publication)
        envelope = publication.envelope
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.nonce == envelope.nonce
                )
            )
        )
        existing = result.scalar_one_or_none()
        distribution = PlatformPluginDistributionV2(
            descriptor=PluginGenerationDescriptorV2(
                profile_id=publication.snapshot.profile_id,
                generation=publication.snapshot.generation,
                digest=publication.snapshot.digest,
            ),
            snapshot=publication.snapshot,
            envelope=envelope,
        ).to_payload()
        if existing is not None:
            if existing.distribution != distribution:
                raise ValueError("plugin v2 publication nonce belongs to another distribution")
            return cast(PlatformPluginV2PublicationModel, existing)
        model = PlatformPluginV2PublicationModel(
            id=PlatformPluginV2PublicationModel.generate_id(),
            profile_id=publication.snapshot.profile_id,
            generation=publication.snapshot.generation,
            snapshot_digest=publication.snapshot.digest,
            requested_version=envelope.version,
            nonce=envelope.nonce,
            type_url=envelope.type_url,
            distribution=distribution,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def record_publication_and_receipt(
        self,
        publication: PlatformPluginPublicationV2,
        *,
        data_plane_id: str,
    ) -> PlatformPluginLedgerRecordV2:
        """Append a requested distribution and atomically advance its receipt ledger."""
        if not data_plane_id.strip():
            raise ValueError("data_plane_id is required")
        publication_row = await self.record_publication(publication)
        state = await self._record_receipt(
            publication_row,
            publication.receipt,
            data_plane_id=data_plane_id,
        )
        return PlatformPluginLedgerRecordV2(
            publication=publication_row,
            apply_state=state,
        )

    async def last_good_distribution(self, data_plane_id: str) -> dict[str, Any] | None:
        """Return the full distribution referenced by the data plane's retained ACK."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id == data_plane_id
                )
            )
        )
        state = result.scalar_one_or_none()
        if state is None or state.applied_publication_id is None:
            return None
        publication = await self._session.get(
            PlatformPluginV2PublicationModel,
            state.applied_publication_id,
        )
        if publication is None:
            raise RuntimeError("plugin v2 last-good publication is missing")
        return dict(publication.distribution)

    async def _record_receipt(
        self,
        publication: PlatformPluginV2PublicationModel,
        receipt: SnapshotApplyReceiptV2,
        *,
        data_plane_id: str,
    ) -> PlatformPluginV2ApplyStateModel:
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id == data_plane_id
                )
            )
        )
        state = result.scalar_one_or_none()
        applied_publication_id = _applied_publication_id(
            publication,
            receipt,
            state,
        )
        now = datetime.now(UTC)
        values = {
            "requested_publication_id": publication.id,
            "requested_version": receipt.requested_version,
            "requested_digest": receipt.requested_digest,
            "applied_publication_id": applied_publication_id,
            "applied_version": receipt.applied_version,
            "applied_digest": receipt.applied_digest,
            "status": receipt.status.value,
            "error_code": receipt.error_code,
            "error_message": receipt.error_message,
        }
        if state is None:
            state = PlatformPluginV2ApplyStateModel(
                id=PlatformPluginV2ApplyStateModel.generate_id(),
                data_plane_id=data_plane_id,
                last_ack_at=now if receipt.status is ApplyStatusV2.ACK else None,
                **values,
            )
            self._session.add(state)
        else:
            for key, value in values.items():
                setattr(state, key, value)
            if receipt.status is ApplyStatusV2.ACK:
                state.last_ack_at = now
        self._session.add(
            PlatformPluginV2ApplyStateEventModel(
                id=PlatformPluginV2ApplyStateEventModel.generate_id(),
                data_plane_id=data_plane_id,
                **values,
            )
        )
        await self._session.flush()
        return cast(PlatformPluginV2ApplyStateModel, state)


def _validate_receipt(publication: PlatformPluginPublicationV2) -> None:
    receipt = publication.receipt
    envelope = publication.envelope
    if (
        receipt.requested_version != envelope.version
        or receipt.requested_digest != publication.snapshot.digest
        or envelope.snapshot_digest != publication.snapshot.digest
    ):
        raise ValueError("plugin v2 receipt does not match publication")
    if receipt.status is ApplyStatusV2.ACK:
        if (
            receipt.applied_version != receipt.requested_version
            or receipt.applied_digest != receipt.requested_digest
            or receipt.error_code is not None
            or receipt.error_message is not None
        ):
            raise ValueError("plugin v2 ACK receipt is inconsistent")
    elif not receipt.error_code or not receipt.error_message:
        raise ValueError("plugin v2 NACK receipt requires an error code and message")


def _applied_publication_id(
    publication: PlatformPluginV2PublicationModel,
    receipt: SnapshotApplyReceiptV2,
    state: PlatformPluginV2ApplyStateModel | None,
) -> str | None:
    if receipt.status is ApplyStatusV2.ACK:
        return publication.id
    previous_id = None if state is None else state.applied_publication_id
    previous_version = None if state is None else state.applied_version
    previous_digest = None if state is None else state.applied_digest
    if (receipt.applied_version, receipt.applied_digest) != (previous_version, previous_digest):
        raise ValueError("plugin v2 NACK does not retain the recorded last-good publication")
    return previous_id


__all__ = [
    "PYTHON_API_DATA_PLANE_ID_V2",
    "PlatformPluginLedgerRecordV2",
    "PlatformPluginRepositoryV2",
]
