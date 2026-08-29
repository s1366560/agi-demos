"""Durable protocol-v2 publication and data-plane receipt ledger."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    PublicationStatusV2,
    SnapshotApplyReceiptV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginDataPlaneReadinessV2,
    PlatformPluginPublicationPolicyV2,
    PlatformPluginPublicationReadinessV2,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
)


class PlatformPluginLedgerV2Error(ValueError):
    """Stable v2 publication/receipt conflict for control-plane transports."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


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
        *,
        policy: PlatformPluginPublicationPolicyV2 | None = None,
        now: datetime | None = None,
    ) -> PlatformPluginV2PublicationModel:
        """Append one complete requested distribution, deduping only its nonce."""
        _validate_receipt(publication)
        resolved_policy = policy or PlatformPluginPublicationPolicyV2.local_default()
        requested_at = _utc_now_v2(now)
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
            _validate_existing_policy_v2(existing, resolved_policy)
            return cast(PlatformPluginV2PublicationModel, existing)
        await self._degrade_superseded_publications(requested_at)
        model = PlatformPluginV2PublicationModel(
            id=PlatformPluginV2PublicationModel.generate_id(),
            profile_id=publication.snapshot.profile_id,
            generation=publication.snapshot.generation,
            snapshot_digest=publication.snapshot.digest,
            requested_version=envelope.version,
            nonce=envelope.nonce,
            type_url=envelope.type_url,
            distribution=distribution,
            required_data_plane_ids=list(resolved_policy.required_data_plane_ids),
            ack_deadline_at=resolved_policy.deadline_from(requested_at),
            status=PublicationStatusV2.RECONCILING.value,
            ready_at=None,
            status_updated_at=requested_at,
            republished_from_id=None,
            created_at=requested_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def record_publication_and_receipt(
        self,
        publication: PlatformPluginPublicationV2,
        *,
        data_plane_id: str,
        policy: PlatformPluginPublicationPolicyV2 | None = None,
        now: datetime | None = None,
    ) -> PlatformPluginLedgerRecordV2:
        """Append a requested distribution and atomically advance its receipt ledger."""
        if not data_plane_id.strip():
            raise ValueError("data_plane_id is required")
        publication_row = await self.record_publication(
            publication,
            policy=policy,
            now=now,
        )
        if data_plane_id not in publication_row.required_data_plane_ids:
            raise ValueError("data_plane_id is not required by the plugin v2 publication")
        state = await self._record_receipt(
            publication_row,
            publication.receipt,
            data_plane_id=data_plane_id,
            now=now,
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

    async def latest_requested_distribution(self) -> dict[str, Any] | None:
        """Return the newest complete requested distribution for polling data planes."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel).order_by(
                    PlatformPluginV2PublicationModel.requested_version.desc(),
                    PlatformPluginV2PublicationModel.created_at.desc(),
                    PlatformPluginV2PublicationModel.id.desc(),
                )
            )
        )
        publication = result.scalars().first()
        return None if publication is None else dict(publication.distribution)

    async def latest_publication_readiness(
        self,
        *,
        now: datetime | None = None,
    ) -> PlatformPluginPublicationReadinessV2 | None:
        """Return and refresh readiness for the newest requested publication."""
        publication = await self._latest_publication(for_update=True)
        if publication is None:
            return None
        return await self._publication_readiness_row(publication, _utc_now_v2(now))

    async def publication_readiness(
        self,
        nonce: str,
        *,
        now: datetime | None = None,
    ) -> PlatformPluginPublicationReadinessV2:
        """Return and refresh readiness for one exact publication nonce."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel)
                .where(PlatformPluginV2PublicationModel.nonce == nonce)
                .with_for_update()
            )
        )
        publication = result.scalar_one_or_none()
        if publication is None:
            raise PlatformPluginLedgerV2Error(
                "publication_not_found",
                "plugin v2 publication nonce is unknown",
            )
        return await self._publication_readiness_row(publication, _utc_now_v2(now))

    async def reconcile_publication_deadlines(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Persist terminal readiness for a bounded batch of overdue publications."""
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("plugin v2 deadline reconciliation limit must be between 1 and 1000")
        observed_at = _utc_now_v2(now)
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel)
                .where(
                    PlatformPluginV2PublicationModel.status
                    == PublicationStatusV2.RECONCILING.value,
                    PlatformPluginV2PublicationModel.ack_deadline_at <= observed_at,
                )
                .order_by(
                    PlatformPluginV2PublicationModel.ack_deadline_at,
                    PlatformPluginV2PublicationModel.requested_version,
                    PlatformPluginV2PublicationModel.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        publications = list(result.scalars())
        for publication in publications:
            await self._refresh_publication_status(publication, observed_at)
        return len(publications)

    async def republish_last_globally_ready(
        self,
        *,
        policy: PlatformPluginPublicationPolicyV2 | None = None,
        nonce: str | None = None,
        now: datetime | None = None,
    ) -> PlatformPluginV2PublicationModel:
        """Create an auditable publication from the latest snapshot that reached ready."""
        requested_at = _utc_now_v2(now)
        resolved_policy = policy or PlatformPluginPublicationPolicyV2.local_default()
        source_result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel)
                .where(PlatformPluginV2PublicationModel.ready_at.is_not(None))
                .order_by(
                    PlatformPluginV2PublicationModel.requested_version.desc(),
                    PlatformPluginV2PublicationModel.ready_at.desc(),
                    PlatformPluginV2PublicationModel.id.desc(),
                )
                .with_for_update()
            )
        )
        source = source_result.scalars().first()
        if source is None:
            raise PlatformPluginLedgerV2Error(
                "globally_ready_not_found",
                "no globally-ready plugin v2 publication is available",
            )
        latest = await self._latest_publication(for_update=True)
        if latest is None:
            raise RuntimeError("plugin v2 ready publication disappeared")
        requested_version = latest.requested_version + 1
        publication_nonce = nonce or f"republish-{token_urlsafe(24)}"
        _validate_nonce_v2(publication_nonce)
        nonce_result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.nonce == publication_nonce
                )
            )
        )
        if nonce_result.scalar_one_or_none() is not None:
            raise PlatformPluginLedgerV2Error(
                "publication_nonce_conflict",
                "plugin v2 republish nonce is already in use",
            )
        distribution = deepcopy(source.distribution)
        envelope = distribution.get("envelope")
        if not isinstance(envelope, dict):
            raise RuntimeError("plugin v2 ready distribution has no envelope")
        envelope["version"] = requested_version
        envelope["nonce"] = publication_nonce
        await self._degrade_superseded_publications(requested_at)
        model = PlatformPluginV2PublicationModel(
            id=PlatformPluginV2PublicationModel.generate_id(),
            profile_id=source.profile_id,
            generation=source.generation,
            snapshot_digest=source.snapshot_digest,
            requested_version=requested_version,
            nonce=publication_nonce,
            type_url=source.type_url,
            distribution=distribution,
            required_data_plane_ids=list(resolved_policy.required_data_plane_ids),
            ack_deadline_at=resolved_policy.deadline_from(requested_at),
            status=PublicationStatusV2.RECONCILING.value,
            ready_at=None,
            status_updated_at=requested_at,
            republished_from_id=source.id,
            created_at=requested_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def record_data_plane_receipt(
        self,
        *,
        data_plane_id: str,
        nonce: str,
        receipt: SnapshotApplyReceiptV2,
        now: datetime | None = None,
    ) -> PlatformPluginV2ApplyStateModel:
        """Bind one external receipt to the exact immutable publication nonce."""
        if not data_plane_id.strip():
            raise PlatformPluginLedgerV2Error("data_plane_id_invalid", "data_plane_id is required")
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel)
                .where(PlatformPluginV2PublicationModel.nonce == nonce)
                .with_for_update()
            )
        )
        publication = result.scalar_one_or_none()
        if publication is None:
            raise PlatformPluginLedgerV2Error(
                "publication_not_found",
                "plugin v2 publication nonce is unknown",
            )
        if data_plane_id not in publication.required_data_plane_ids:
            raise PlatformPluginLedgerV2Error(
                "data_plane_not_required",
                "plugin v2 data plane is not registered for this publication",
            )
        await self._validate_current_publication(publication)
        _validate_external_receipt(publication, receipt)
        state_result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id == data_plane_id
                )
            )
        )
        state = state_result.scalar_one_or_none()
        if state is not None:
            if receipt.requested_version < state.requested_version:
                raise PlatformPluginLedgerV2Error(
                    "stale_receipt",
                    "plugin v2 receipt requested version is older than recorded state",
                )
            if (
                receipt.requested_version == state.requested_version
                and receipt.requested_digest != state.requested_digest
            ):
                raise PlatformPluginLedgerV2Error(
                    "version_digest_conflict",
                    "plugin v2 receipt changes digest within a requested version",
                )
        try:
            return await self._record_receipt(
                publication,
                receipt,
                data_plane_id=data_plane_id,
                now=now,
            )
        except ValueError as exc:
            raise PlatformPluginLedgerV2Error("last_good_mismatch", str(exc)) from exc

    async def _record_receipt(
        self,
        publication: PlatformPluginV2PublicationModel,
        receipt: SnapshotApplyReceiptV2,
        *,
        data_plane_id: str,
        now: datetime | None = None,
    ) -> PlatformPluginV2ApplyStateModel:
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id == data_plane_id
                )
            )
        )
        state = result.scalar_one_or_none()
        recorded_at = _utc_now_v2(now)
        if state is not None and _state_matches_receipt(publication, receipt, state):
            await self._refresh_publication_status(publication, recorded_at)
            return cast(PlatformPluginV2ApplyStateModel, state)
        applied_publication_id = _applied_publication_id(
            publication,
            receipt,
            state,
        )
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
                last_ack_at=recorded_at if receipt.status is ApplyStatusV2.ACK else None,
                created_at=recorded_at,
                updated_at=recorded_at,
                **values,
            )
            self._session.add(state)
        else:
            for key, value in values.items():
                setattr(state, key, value)
            state.updated_at = recorded_at
            if receipt.status is ApplyStatusV2.ACK:
                state.last_ack_at = recorded_at
        self._session.add(
            PlatformPluginV2ApplyStateEventModel(
                id=PlatformPluginV2ApplyStateEventModel.generate_id(),
                data_plane_id=data_plane_id,
                recorded_at=recorded_at,
                **values,
            )
        )
        await self._session.flush()
        await self._refresh_publication_status(publication, recorded_at)
        return cast(PlatformPluginV2ApplyStateModel, state)

    async def _latest_publication(
        self,
        *,
        for_update: bool,
    ) -> PlatformPluginV2PublicationModel | None:
        statement = select(PlatformPluginV2PublicationModel).order_by(
            PlatformPluginV2PublicationModel.requested_version.desc(),
            PlatformPluginV2PublicationModel.created_at.desc(),
            PlatformPluginV2PublicationModel.id.desc(),
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(refresh_select_statement(statement))
        return cast("PlatformPluginV2PublicationModel | None", result.scalars().first())

    async def _validate_current_publication(
        self,
        publication: PlatformPluginV2PublicationModel,
    ) -> None:
        latest = await self._latest_publication(for_update=False)
        if latest is None or latest.id == publication.id:
            return
        if latest.requested_version >= publication.requested_version:
            raise PlatformPluginLedgerV2Error(
                "stale_receipt",
                "plugin v2 receipt targets a superseded publication",
            )

    async def _degrade_superseded_publications(self, now: datetime) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.status == PublicationStatusV2.RECONCILING.value
                )
            )
        )
        for publication in result.scalars():
            publication.status = PublicationStatusV2.DEGRADED.value
            publication.status_updated_at = now
        await self._session.flush()

    async def _publication_readiness_row(
        self,
        publication: PlatformPluginV2PublicationModel,
        now: datetime,
    ) -> PlatformPluginPublicationReadinessV2:
        await self._refresh_publication_status(publication, now)
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateEventModel)
                .where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id == publication.id,
                    PlatformPluginV2ApplyStateEventModel.data_plane_id.in_(
                        publication.required_data_plane_ids
                    ),
                )
                .order_by(
                    PlatformPluginV2ApplyStateEventModel.recorded_at,
                    PlatformPluginV2ApplyStateEventModel.id,
                )
            )
        )
        state_by_plane = {event.data_plane_id: event for event in result.scalars()}
        source_nonce: str | None = None
        if publication.republished_from_id is not None:
            source = await self._session.get(
                PlatformPluginV2PublicationModel,
                publication.republished_from_id,
            )
            if source is None:
                raise RuntimeError("plugin v2 republish source is missing")
            source_nonce = source.nonce
        data_planes: list[PlatformPluginDataPlaneReadinessV2] = []
        for data_plane_id in publication.required_data_plane_ids:
            state = state_by_plane.get(data_plane_id)
            data_planes.append(
                PlatformPluginDataPlaneReadinessV2(
                    data_plane_id=data_plane_id,
                    status=None if state is None else ApplyStatusV2(state.status),
                    requested_version=None if state is None else state.requested_version,
                    requested_digest=None if state is None else state.requested_digest,
                    applied_version=None if state is None else state.applied_version,
                    applied_digest=None if state is None else state.applied_digest,
                    error_code=None if state is None else state.error_code,
                    error_message=None if state is None else state.error_message,
                )
            )
        return PlatformPluginPublicationReadinessV2(
            publication_id=publication.id,
            profile_id=publication.profile_id,
            generation=publication.generation,
            requested_version=publication.requested_version,
            snapshot_digest=publication.snapshot_digest,
            nonce=publication.nonce,
            republished_from_nonce=source_nonce,
            required_data_plane_ids=tuple(publication.required_data_plane_ids),
            ack_deadline_at=_as_utc_v2(publication.ack_deadline_at),
            status=PublicationStatusV2(publication.status),
            ready_at=None if publication.ready_at is None else _as_utc_v2(publication.ready_at),
            data_planes=tuple(data_planes),
        )

    async def _refresh_publication_status(
        self,
        publication: PlatformPluginV2PublicationModel,
        now: datetime,
    ) -> None:
        latest = await self._latest_publication(for_update=False)
        if latest is not None and latest.id != publication.id:
            return
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.requested_publication_id == publication.id,
                    PlatformPluginV2ApplyStateModel.data_plane_id.in_(
                        publication.required_data_plane_ids
                    ),
                )
            )
        )
        state_by_plane = {state.data_plane_id: state for state in result.scalars()}
        required_states = [
            state_by_plane.get(data_plane_id)
            for data_plane_id in publication.required_data_plane_ids
        ]
        all_ack = all(
            state is not None
            and state.status == ApplyStatusV2.ACK.value
            and state.requested_version == publication.requested_version
            and state.requested_digest == publication.snapshot_digest
            and state.applied_version == publication.requested_version
            and state.applied_digest == publication.snapshot_digest
            for state in required_states
        )
        any_nack = any(
            state is not None and state.status == ApplyStatusV2.NACK.value
            for state in required_states
        )
        deadline = _as_utc_v2(publication.ack_deadline_at)
        publication.ack_deadline_at = deadline
        if all_ack:
            status = PublicationStatusV2.READY
        elif any_nack or now >= deadline:
            status = PublicationStatusV2.DEGRADED
        else:
            status = PublicationStatusV2.RECONCILING
        if publication.status != status.value:
            publication.status = status.value
            publication.status_updated_at = now
        if status is PublicationStatusV2.READY and publication.ready_at is None:
            publication.ready_at = now
        await self._session.flush()


def _utc_now_v2(value: datetime | None) -> datetime:
    now = datetime.now(UTC) if value is None else value
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("plugin v2 publication timestamps must include a timezone")
    return now.astimezone(UTC)


def _as_utc_v2(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_existing_policy_v2(
    publication: PlatformPluginV2PublicationModel,
    policy: PlatformPluginPublicationPolicyV2,
) -> None:
    if tuple(publication.required_data_plane_ids) != policy.required_data_plane_ids:
        raise ValueError("plugin v2 publication nonce cannot change its required data-plane roster")
    publication.created_at = _as_utc_v2(publication.created_at)
    publication.ack_deadline_at = _as_utc_v2(publication.ack_deadline_at)
    expected_deadline = policy.deadline_from(publication.created_at)
    if publication.ack_deadline_at != expected_deadline:
        raise ValueError("plugin v2 publication nonce cannot change its ACK deadline")


def _validate_nonce_v2(nonce: str) -> None:
    if not nonce or len(nonce) > 128:
        raise PlatformPluginLedgerV2Error(
            "publication_nonce_invalid",
            "plugin v2 publication nonce must be between 1 and 128 characters",
        )


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


def _validate_external_receipt(
    publication: PlatformPluginV2PublicationModel,
    receipt: SnapshotApplyReceiptV2,
) -> None:
    if (
        receipt.requested_version != publication.requested_version
        or receipt.requested_digest != publication.snapshot_digest
    ):
        raise PlatformPluginLedgerV2Error(
            "receipt_publication_mismatch",
            "plugin v2 receipt does not match publication",
        )
    if receipt.status is ApplyStatusV2.ACK:
        if (
            receipt.applied_version != receipt.requested_version
            or receipt.applied_digest != receipt.requested_digest
            or receipt.error_code is not None
            or receipt.error_message is not None
        ):
            raise PlatformPluginLedgerV2Error(
                "receipt_invalid",
                "plugin v2 ACK receipt is inconsistent",
            )
    elif not receipt.error_code or not receipt.error_message:
        raise PlatformPluginLedgerV2Error(
            "receipt_invalid",
            "plugin v2 NACK receipt requires an error code and message",
        )


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


def _state_matches_receipt(
    publication: PlatformPluginV2PublicationModel,
    receipt: SnapshotApplyReceiptV2,
    state: PlatformPluginV2ApplyStateModel,
) -> bool:
    return (
        state.requested_publication_id == publication.id
        and state.requested_version == receipt.requested_version
        and state.requested_digest == receipt.requested_digest
        and state.applied_version == receipt.applied_version
        and state.applied_digest == receipt.applied_digest
        and state.status == receipt.status.value
        and state.error_code == receipt.error_code
        and state.error_message == receipt.error_message
    )


__all__ = [
    "PYTHON_API_DATA_PLANE_ID_V2",
    "PlatformPluginDataPlaneReadinessV2",
    "PlatformPluginLedgerRecordV2",
    "PlatformPluginLedgerV2Error",
    "PlatformPluginPublicationPolicyV2",
    "PlatformPluginPublicationReadinessV2",
    "PlatformPluginRepositoryV2",
]
