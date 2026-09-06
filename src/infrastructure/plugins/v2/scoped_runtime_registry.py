"""Independent Python scope authorities, without global route publication or fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field

from src.domain.model.plugins.generated_v2 import (
    ControlPlaneEnvelopeV2,
    DataPlaneTargetV2,
    ProfileSnapshotV2,
    ScopeV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .artifacts import PluginArtifactResolverV2
from .lifecycle_tasks import OwnedLifecycleTaskV2
from .protocol import parse_profile_snapshot_v2, profile_snapshot_v2_to_payload
from .reconciler import PreparedGenerationPublicationV2
from .route_authority import ROUTE_AUTHORITY_CATALOG_SERVICE_V2
from .route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from .runtime import (
    GenerationLeaseV2,
    LoaderV2,
    PluginDefinitionV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)
from .runtime_contracts import ModuleCatalogEntryV2
from .runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)
from .scope import scope_key_v2, validate_scope_v2

_GLOBAL_ROUTE_SERVICES = frozenset(
    {ROUTE_TABLE_BUILDER_SERVICE_V2, ROUTE_AUTHORITY_CATALOG_SERVICE_V2}
)


@dataclass(eq=False)
class _ScopeSlot:
    host: PlatformPluginRuntimeHostV2
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    retired: bool = False

    def require_active(self) -> None:
        if self.retired:
            raise RuntimeV2Error("scope_retired", "scope authority has been retired")

    async def stage(self, _generation: RuntimeGenerationV2) -> PreparedGenerationPublicationV2:
        self.require_active()

        async def rollback() -> None:
            return None

        return PreparedGenerationPublicationV2(commit=self.require_active, rollback=rollback)

    async def drain(self) -> None:
        async with self.lock:
            await self.host.close()


@dataclass(frozen=True)
class ScopedRuntimeHostV2:
    """Bind exact reservations to one slot incarnation, including its leased retired generations."""

    _slot: _ScopeSlot

    async def acquire(self) -> GenerationLeaseV2:
        async with self._slot.lock:
            self._slot.require_active()
            lease = await self._slot.host.acquire()
            try:
                self._slot.require_active()
            except BaseException:
                await lease.release()
                raise
            return lease

    async def acquire_exact(
        self, generation: RuntimeGenerationV2, descriptor: PluginGenerationDescriptorV2
    ) -> GenerationLeaseV2:
        return await self._slot.host.acquire_exact(generation, descriptor)

    def distribution_for_generation(
        self, generation: RuntimeGenerationV2
    ) -> PlatformPluginDistributionV2:
        return self._slot.host.distribution_for_generation(generation)


@dataclass
class _ReservationClaimV2:
    claimed: bool = False


@dataclass(frozen=True)
class ScopedRuntimeReservationV2:
    """An acquired lifecycle capability; authentication and durable admission belong to callers."""

    scope: ScopeV2
    host: ScopedRuntimeHostV2
    lease: GenerationLeaseV2
    _claim: _ReservationClaimV2 = field(
        default_factory=_ReservationClaimV2, compare=False, repr=False
    )

    def claim(self) -> None:
        """Transfer this acquired lease into exactly one boundary without an await gap."""
        # Lease has no public release-state API; prevent claim during its owned release task.
        releasing = self.lease._released or self.lease._release_task.started  # pyright: ignore[reportPrivateUsage]
        if self._claim.claimed or releasing:
            raise RuntimeV2Error(
                "scope_reservation_consumed", "scope reservation is already consumed"
            )
        self._claim.claimed = True


class ScopedRuntimeRegistryV2:
    """Own one host per exact scope; callers own authentication and durable publication."""

    def __init__(
        self,
        definitions: Sequence[PluginDefinitionV2] = (),
        *,
        target_catalog: Mapping[str, ModuleCatalogEntryV2] | None = None,
        artifact_resolver: PluginArtifactResolverV2 | None = None,
        definitions_factory: Callable[[ScopeV2], Sequence[PluginDefinitionV2]] | None = None,
    ) -> None:
        if definitions and definitions_factory is not None:
            raise ValueError("scoped definitions require either fixed definitions or a factory")
        self._definitions = tuple(definitions)
        self._definitions_factory = definitions_factory
        self._catalog = None if target_catalog is None else dict(target_catalog)
        self._resolver = artifact_resolver
        self._slots: dict[str, _ScopeSlot] = {}
        self._retirements: dict[str, set[OwnedLifecycleTaskV2]] = {}
        self._retirement_errors: list[BaseException] = []
        self._closed = False
        self._closing = OwnedLifecycleTaskV2(self._drain_all, name="scoped-runtime-close-v2")

    async def publish(
        self, scope: ScopeV2, snapshot: ProfileSnapshotV2, envelope: ControlPlaneEnvelopeV2
    ) -> PlatformPluginPublicationV2:
        """Validate scope containment before any apply; retain last-good on loader NACK."""
        canonical = validate_scope_v2(scope)
        validated = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot))
        _validate_snapshot_scope(canonical, validated)
        if self._closed:
            raise RuntimeV2Error("scope_registry_closed", "scope registry is closed")
        key = scope_key_v2(canonical)
        slot = self._slots.get(key)
        if slot is None:
            definitions = (
                self._definitions
                if self._definitions_factory is None
                else tuple(self._definitions_factory(canonical))
            )
            slot = _ScopeSlot(
                PlatformPluginRuntimeHostV2(
                    loader=LoaderV2(
                        definitions,
                        target=DataPlaneTargetV2.PYTHON,
                        target_catalog=self._catalog,
                        artifact_resolver=self._resolver,
                    )
                )
            )
            self._slots[key] = slot
        async with slot.lock:
            slot.require_active()
            return await slot.host.apply(validated, envelope, publication_stager=slot.stage)

    async def acquire(self, scope: ScopeV2) -> GenerationLeaseV2:
        """Lease only this exact authority; ancestors are never host fallbacks."""
        return (await self.acquire_bound(scope)).lease

    async def acquire_bound(self, scope: ScopeV2) -> ScopedRuntimeReservationV2:
        """Capture the host and lease under the same slot lock, never rebind by scope later."""
        canonical = validate_scope_v2(scope)
        key = scope_key_v2(canonical)
        slot = self._slots.get(key)
        if self._closed or slot is None:
            raise RuntimeV2Error("scope_unavailable", "scope authority is unavailable")
        host = ScopedRuntimeHostV2(slot)
        lease = await host.acquire()
        return ScopedRuntimeReservationV2(canonical, host, lease)

    async def close_scope(self, scope: ScopeV2) -> None:
        """Detach immediately; an explicit later publish may create a fresh authority."""
        key = scope_key_v2(scope)
        slot = self._slots.pop(key, None)
        if slot is not None:
            self._retire(key, slot)
        pending = tuple(self._retirements.get(key, ()))

        async def drain_scope() -> None:
            errors: list[BaseException] = []
            for retirement in pending:
                try:
                    await retirement.wait()
                except BaseException as error:
                    errors.append(error)
            if errors:
                raise BaseExceptionGroup("scope retirement failed", errors)

        # Aggregate all accepted retirements, while preserving caller cancellation.
        # Settled failures are replayed by close(), not by later empty close_scope calls.
        await OwnedLifecycleTaskV2(drain_scope, name="scoped-runtime-wait-v2").wait()

    async def close(self) -> None:
        """Reject new work and observe every accepted retirement despite caller cancellation."""
        if not self._closed:
            self._closed = True
            slots = tuple(self._slots.items())
            self._slots.clear()
            for key, slot in slots:
                self._retire(key, slot)
        await self._closing.wait()

    def _retire(self, key: str, slot: _ScopeSlot) -> OwnedLifecycleTaskV2:
        slot.retired = True

        async def drain() -> None:
            try:
                await slot.drain()
            except BaseException as error:
                self._retirement_errors.append(error)
                raise
            finally:
                pending = self._retirements[key]
                pending.remove(retirement)
                if not pending:
                    del self._retirements[key]

        retirement = OwnedLifecycleTaskV2(drain, name="scoped-runtime-retire-v2")
        self._retirements.setdefault(key, set()).add(retirement)
        retirement.start()
        return retirement

    async def _drain_all(self) -> None:
        pending = tuple(task for tasks in self._retirements.values() for task in tasks)
        for retirement in pending:
            # The owned retirement records its original error before settling.
            with suppress(BaseException):
                await retirement.wait()
        if self._retirement_errors:
            raise BaseExceptionGroup("scope registry retirement failed", self._retirement_errors)


def _validate_snapshot_scope(scope: ScopeV2, snapshot: ProfileSnapshotV2) -> None:
    modules = {
        (manifest.plugin_id, module.module_ref): module
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    for entry in snapshot.entries:
        ancestor = validate_scope_v2(entry.scope)
        if any(
            getattr(ancestor, field) is not None
            and getattr(ancestor, field) != getattr(scope, field)
            for field in ("tenant_id", "project_id", "session_id")
        ):
            raise RuntimeV2Error("scope_snapshot_mismatch", "snapshot contains a foreign scope")
        module = modules.get((entry.plugin_ref, entry.module_ref))
        if module is None or DataPlaneTargetV2.PYTHON not in module.targets:
            continue
        contracts = module.contract.services
        services = {item.service for item in (*contracts.provides, *contracts.requires)}
        if services & _GLOBAL_ROUTE_SERVICES:
            raise RuntimeV2Error(
                "scope_global_route_forbidden", "scoped hosts cannot contribute global HTTP routes"
            )
