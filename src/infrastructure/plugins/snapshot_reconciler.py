"""Python data-plane reconciliation for canonical profile snapshots.

The reconciler is the in-process counterpart of the Rust sidecar
``PlatformPluginSnapshotReconciler``: it validates the control-plane envelope,
prepares the new generation in a staging registry before mutating runtime
state, and retains the last-good generation on any failure. ACK/NACK receipts
are returned to the caller, which persists them through the control-plane
service.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .compatibility import (
    Disposable,
    PreparedLlmProvider,
    activate_profile_snapshot,
    prepare_profile_snapshot,
)
from .context import CapabilityRegistry
from .llm_adapters import LlmAdapterFactory, LlmAdapterProviderRegistry
from .profile import PROFILE_SNAPSHOT_TYPE_URL, ControlPlaneEnvelope, ProfileSnapshot


@dataclass(frozen=True)
class SnapshotApplyReceipt:
    """Outcome of one data-plane snapshot apply attempt."""

    status: str
    requested_version: int
    requested_digest: str
    applied_version: int | None
    applied_digest: str | None
    error_message: str | None = None

    @property
    def accepted(self) -> bool:
        """Return whether the snapshot generation was applied."""
        return self.status == "ack"


@dataclass
class _ActiveGeneration:
    version: int
    digest: str
    capabilities: CapabilityRegistry
    adapter_owners: dict[str, str]
    dispose_adapters: Disposable


class PlatformPluginSnapshotReconciler:
    """Generational snapshot activation with last-good retention.

    Each accepted generation activates into a fresh staging
    :class:`CapabilityRegistry`, so a rejected snapshot can never disturb the
    active capability set. LLM adapter providers live in one long-lived
    registry shared with the provider manager; the reconciler performs an
    owner-checked handoff for those entries.
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry | None = None,
        *,
        adapter_registry: LlmAdapterProviderRegistry | None = None,
        llm_adapter_factory: LlmAdapterFactory | None = None,
    ) -> None:
        self._initial_capabilities = capability_registry or CapabilityRegistry()
        self._adapter_registry = adapter_registry
        self._llm_adapter_factory = llm_adapter_factory
        self._lock = threading.RLock()
        self._active: _ActiveGeneration | None = None

    @property
    def capability_registry(self) -> CapabilityRegistry:
        """Return the active generation's capability registry."""
        with self._lock:
            if self._active is None:
                return self._initial_capabilities
            return self._active.capabilities

    @property
    def applied_version(self) -> int | None:
        """Return the currently applied snapshot version, if any."""
        with self._lock:
            return None if self._active is None else self._active.version

    @property
    def applied_digest(self) -> str | None:
        """Return the currently applied snapshot digest, if any."""
        with self._lock:
            return None if self._active is None else self._active.digest

    def apply(
        self,
        snapshot: ProfileSnapshot,
        envelope: ControlPlaneEnvelope,
    ) -> SnapshotApplyReceipt:
        """Validate, activate, and atomically swap one snapshot generation."""
        with self._lock:
            invalid = self._validate_envelope(snapshot, envelope)
            if invalid is not None:
                return invalid

            existing = self._check_active(envelope)
            if existing is not None:
                return existing

            try:
                prepared = prepare_profile_snapshot(
                    snapshot,
                    llm_adapter_factory=self._llm_adapter_factory,
                )
            except Exception as exc:
                # Pure validation failed: nothing was mutated anywhere.
                return self._nack(envelope, f"snapshot validation failed: {exc}")

            conflict = self._check_adapter_handoff(prepared.llm_providers)
            if conflict is not None:
                return self._nack(envelope, conflict)

            staging = CapabilityRegistry()
            try:
                activate_profile_snapshot(
                    snapshot,
                    staging,
                    prepared=prepared,
                )
            except Exception as exc:
                # Staging is isolated: a failure leaves the active generation
                # and the shared adapter registry untouched.
                return self._nack(envelope, f"snapshot activation failed: {exc}")

            adapter_dispose = self._commit_adapter_handoff(prepared.llm_providers)

            previous = self._active
            self._active = _ActiveGeneration(
                version=envelope.version,
                digest=snapshot.digest,
                capabilities=staging,
                adapter_owners={
                    provider.capability_id: provider.manifest_id
                    for provider in prepared.llm_providers
                },
                dispose_adapters=adapter_dispose,
            )
            # The retired registry is dropped, not disposed: consumers holding
            # it keep their pinned generation valid until they release it.
            _ = previous
            return self._ack(envelope)

    def dispose(self) -> None:
        """Tear down the active generation, primarily for shutdown and tests."""
        with self._lock:
            if self._active is not None:
                self._active.dispose_adapters()
                self._active = None

    def _check_adapter_handoff(
        self,
        providers: tuple[PreparedLlmProvider, ...],
    ) -> str | None:
        """Fail fast when a provider id is owned by a non-generation actor."""
        if self._adapter_registry is None:
            return None
        active_owners = {} if self._active is None else self._active.adapter_owners
        wanted = {provider.capability_id: provider.manifest_id for provider in providers}
        for capability_id, manifest_id in sorted(wanted.items()):
            owner = self._adapter_registry.owner_of(capability_id)
            if owner is None or owner == manifest_id:
                continue
            if owner.startswith("llm-provider:"):
                # Manager-owned rehearsal registrations defer to the profile.
                continue
            if active_owners.get(capability_id) == owner:
                continue
            return f"LLM adapter {capability_id} is owned by {owner}"
        return None

    def _commit_adapter_handoff(
        self,
        providers: tuple[PreparedLlmProvider, ...],
    ) -> Disposable:
        """Apply the adapter ownership diff after pre-validation."""
        if self._adapter_registry is None:
            return lambda: None
        registry = self._adapter_registry
        active_owners = dict({} if self._active is None else self._active.adapter_owners)
        wanted = {
            provider.capability_id: (provider.manifest_id, provider.provider)
            for provider in providers
        }
        removed = [key for key in active_owners if key not in wanted]
        for capability_id in removed:
            registry.unregister(capability_id, owner=active_owners[capability_id])
        for capability_id, (manifest_id, provider) in sorted(wanted.items()):
            owner = registry.owner_of(capability_id)
            if owner is None:
                _ = registry.register(capability_id, provider, owner=manifest_id)
            elif owner == manifest_id:
                _ = registry.replace(capability_id, provider, owner=manifest_id)
            else:
                registry.unregister(capability_id, owner=owner)
                _ = registry.register(capability_id, provider, owner=manifest_id)

        def dispose() -> None:
            for capability_id, (manifest_id, _provider) in wanted.items():
                registry.unregister(capability_id, owner=manifest_id)

        return dispose

    def _validate_envelope(
        self,
        snapshot: ProfileSnapshot,
        envelope: ControlPlaneEnvelope,
    ) -> SnapshotApplyReceipt | None:
        if envelope.type_url != PROFILE_SNAPSHOT_TYPE_URL:
            return self._nack(
                envelope,
                f"unsupported snapshot type_url: {envelope.type_url}",
            )
        if envelope.snapshot_digest != snapshot.digest:
            return self._nack(
                envelope,
                "envelope digest does not match snapshot payload",
            )
        return None

    def _ack(self, envelope: ControlPlaneEnvelope) -> SnapshotApplyReceipt:
        return SnapshotApplyReceipt(
            status="ack",
            requested_version=envelope.version,
            requested_digest=envelope.snapshot_digest,
            applied_version=envelope.version,
            applied_digest=envelope.snapshot_digest,
        )

    def _check_active(self, envelope: ControlPlaneEnvelope) -> SnapshotApplyReceipt | None:
        """Short-circuit envelope handling against the active generation."""
        active = self._active
        if active is None:
            return None
        if envelope.version < active.version:
            return self._nack(
                envelope,
                f"stale snapshot version {envelope.version}; applied version is {active.version}",
            )
        if envelope.version == active.version:
            if envelope.snapshot_digest == active.digest:
                return self._ack(envelope)
            return self._nack(
                envelope,
                f"snapshot digest changed within version {envelope.version}",
            )
        if envelope.snapshot_digest == active.digest:
            # Content-addressed digests are equal, so the active generation
            # already represents this exact composition; adopt the newer
            # version without re-activation.
            self._active = _ActiveGeneration(
                version=envelope.version,
                digest=active.digest,
                capabilities=active.capabilities,
                adapter_owners=active.adapter_owners,
                dispose_adapters=active.dispose_adapters,
            )
            return self._ack(envelope)
        return None

    def _nack(
        self,
        envelope: ControlPlaneEnvelope,
        error_message: str,
    ) -> SnapshotApplyReceipt:
        active = self._active
        return SnapshotApplyReceipt(
            status="nack",
            requested_version=envelope.version,
            requested_digest=envelope.snapshot_digest,
            applied_version=None if active is None else active.version,
            applied_digest=None if active is None else active.digest,
            error_message=error_message,
        )
