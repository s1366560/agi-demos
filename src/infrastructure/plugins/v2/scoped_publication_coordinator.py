"""Durable request/apply/receipt coordination for already-authorized private scopes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ProfileSnapshotV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)

from .lifecycle_tasks import OwnedLifecycleTaskV2
from .protocol import (
    control_envelope_v2,
    control_envelope_v2_to_payload,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)
from .runtime import GenerationLeaseV2, RuntimeV2Error
from .runtime_host import PlatformPluginPublicationV2
from .scope import scope_key_v2, validate_scope_v2
from .scoped_runtime_registry import ScopedRuntimeRegistryV2, ScopedRuntimeReservationV2


@dataclass
class _PublicationSlot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: PlatformPluginPublicationV2 | None = None
    admitted: PlatformPluginPublicationV2 | None = None
    observed: PlatformPluginPublicationV2 | None = None
    blocked: bool = False


class ScopedPublicationCoordinatorV2:
    """Own a private registry; persistence integrity never grants HTTP authorization."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ScopedRuntimeRegistryV2 | None = None,
        data_plane_id: str = PYTHON_API_DATA_PLANE_ID_V2,
    ) -> None:
        super().__init__()
        self._sessions = session_factory
        self._registry = registry if registry is not None else ScopedRuntimeRegistryV2()
        self._plane = data_plane_id
        self._policy = PlatformPluginPublicationPolicyV2(required_data_plane_ids=(data_plane_id,))
        self._slots: dict[str, _PublicationSlot] = {}
        self._closed = False
        self._cleanup_errors: list[BaseException] = []
        self._closing = OwnedLifecycleTaskV2(self._drain, name="scoped-publication-close-v2")

    def _active(self) -> None:
        if self._closed:
            raise RuntimeV2Error("scope_coordinator_closed", "scope coordinator is closed")

    def _slot(self, scope: ScopeV2) -> _PublicationSlot:
        self._active()
        return self._slots.setdefault(scope_key_v2(scope), _PublicationSlot())

    async def publish(
        self,
        scope: ScopeV2,
        snapshot: ProfileSnapshotV2,
        *,
        expected_desired: DesiredBundleSetV2 | None = None,
    ) -> PlatformPluginPublicationV2:
        canonical = validate_scope_v2(scope)
        frozen = parse_profile_snapshot_v2(deepcopy(profile_snapshot_v2_to_payload(snapshot)))
        desired_fence = deepcopy(expected_desired)
        slot = self._slot(canonical)
        result: list[PlatformPluginPublicationV2] = []

        async def work() -> None:
            async with slot.lock:
                self._active()
                if slot.pending is not None:
                    raise RuntimeV2Error("scope_receipt_pending", "retry the real receipt first")
                async with self._sessions() as session:
                    repository = PlatformPluginRepositoryV2(session, scope=canonical)
                    version = await repository.allocate_publication_version()
                    if desired_fence is not None:
                        current = await PlatformPluginDesiredBundleSetRepositoryV2(
                            session
                        ).current_desired_set(canonical)
                        if current is None or current.desired_set != desired_fence:
                            raise RuntimeV2Error(
                                "scope_desired_changed", "desired source changed before publication"
                            )
                    envelope = control_envelope_v2(frozen, version=version)
                    _ = await repository.record_requested_distribution(
                        frozen, envelope, policy=self._policy
                    )
                    await session.commit()
                # From this point a durable request exists; never admit an unreceipted apply.
                slot.blocked = True
                publication = await self._registry.publish(canonical, frozen, envelope)
                slot.pending = publication
                await self._persist_receipt(canonical, slot)
                result.append(publication)

        await OwnedLifecycleTaskV2(work, name="scoped-publication-apply-v2").wait()
        return result[0]

    async def _persist_receipt(self, scope: ScopeV2, slot: _PublicationSlot) -> None:
        publication = slot.pending
        if publication is None:
            raise RuntimeV2Error("scope_receipt_missing", "no pending apply receipt")
        try:
            async with self._sessions() as session:
                _ = await PlatformPluginRepositoryV2(
                    session, scope=scope
                ).record_data_plane_receipt(
                    data_plane_id=self._plane,
                    nonce=publication.envelope.nonce,
                    receipt=publication.receipt,
                )
                await session.commit()
        except PlatformPluginLedgerV2Error as error:
            if error.code == "stale_receipt":
                # Permanently superseded; explicit new publication may reconcile this process.
                slot.pending = None
            raise
        slot.observed = publication
        if publication.accepted:
            slot.admitted = publication
        slot.pending = None
        slot.blocked = False

    async def retry_receipt(self, scope: ScopeV2) -> PlatformPluginPublicationV2:
        canonical = validate_scope_v2(scope)
        slot = self._slot(canonical)
        result: list[PlatformPluginPublicationV2] = []

        async def work() -> None:
            async with slot.lock:
                self._active()
                publication = slot.pending
                if publication is None:
                    raise RuntimeV2Error("scope_receipt_missing", "no pending apply receipt")
                await self._persist_receipt(canonical, slot)
                result.append(publication)

        await OwnedLifecycleTaskV2(work, name="scoped-publication-receipt-v2").wait()
        return result[0]

    async def acquire(self, scope: ScopeV2) -> GenerationLeaseV2:
        return (await self.acquire_bound(scope)).lease

    async def acquire_bound(self, scope: ScopeV2) -> ScopedRuntimeReservationV2:
        """Return the exact host binding only after all durable admission checks succeed."""
        canonical = validate_scope_v2(scope)
        slot = self._slot(canonical)
        async with slot.lock:
            self._active()
            if slot.blocked or slot.pending is not None or slot.admitted is None:
                raise RuntimeV2Error("scope_not_admitted", "scope has no durable local admission")
            admitted, observed = slot.admitted, slot.observed
            lease: GenerationLeaseV2 | None = None
            try:
                async with self._sessions() as session:
                    binding = ScopeLedgerBindingV2(canonical, PlatformPluginLedgerV2Error)
                    _ = await binding.lock(session)
                    repository = PlatformPluginRepositoryV2(session, scope=canonical)
                    latest = await repository.latest_requested_distribution()
                    last_good = await repository.last_good_distribution(self._plane)
                    if (
                        observed is None
                        or latest is None
                        or last_good is None
                        or latest.get("envelope")
                        != control_envelope_v2_to_payload(observed.envelope)
                        or last_good.get("envelope")
                        != control_envelope_v2_to_payload(admitted.envelope)
                        or last_good.get("snapshot")
                        != profile_snapshot_v2_to_payload(admitted.snapshot)
                    ):
                        raise RuntimeV2Error(
                            "scope_publication_changed", "durable scope identity changed"
                        )
                    reservation = await self._registry.acquire_bound(canonical)
                    lease = reservation.lease
                    descriptor = lease.generation.descriptor
                    if (descriptor.profile_id, descriptor.generation, descriptor.digest) != (
                        admitted.snapshot.profile_id,
                        admitted.snapshot.generation,
                        admitted.snapshot.digest,
                    ):
                        raise RuntimeV2Error(
                            "scope_generation_mismatch", "local generation differs"
                        )
                    await session.commit()
                    self._active()
                return reservation
            except BaseException:
                if lease is not None:
                    try:
                        await lease.release()
                    except BaseException as cleanup_error:
                        self._cleanup_errors.append(cleanup_error)
                raise

    async def close(self) -> None:
        self._closed = True
        await self._closing.wait()

    async def _drain(self) -> None:
        # No new slots can enter after close's synchronous gate.
        for slot in tuple(self._slots.values()):
            async with slot.lock:
                pass
        try:
            await self._registry.close()
        except BaseException as error:
            self._cleanup_errors.append(error)
        if self._cleanup_errors:
            raise BaseExceptionGroup("scoped coordinator cleanup failed", self._cleanup_errors)
