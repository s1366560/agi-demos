"""Python data-plane reconciliation for canonical profile snapshots.

The reconciler is the in-process counterpart of the Rust sidecar
``PlatformPluginSnapshotReconciler``: it validates the control-plane envelope,
prepares the new generation before mutating runtime state, and retains the
last-good generation on any failure. ACK/NACK receipts are returned to the
caller, which persists them through the control-plane service.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .compatibility import Disposable, activate_profile_snapshot
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
    dispose: Disposable


class PlatformPluginSnapshotReconciler:
    """Generational snapshot activation with last-good retention."""

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        *,
        adapter_registry: LlmAdapterProviderRegistry | None = None,
        llm_adapter_factory: LlmAdapterFactory | None = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._adapter_registry = adapter_registry
        self._llm_adapter_factory = llm_adapter_factory
        self._lock = threading.RLock()
        self._active: _ActiveGeneration | None = None

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
                dispose_next = activate_profile_snapshot(
                    snapshot,
                    self._capability_registry,
                    adapter_registry=self._adapter_registry,
                    llm_adapter_factory=self._llm_adapter_factory,
                )
            except Exception as exc:
                # Preparation failed before any runtime swap: the last-good
                # generation stays active untouched.
                return self._nack(envelope, f"snapshot activation failed: {exc}")

            previous = self._active
            if previous is not None:
                previous.dispose()
            self._active = _ActiveGeneration(
                version=envelope.version,
                digest=snapshot.digest,
                dispose=dispose_next,
            )
            return self._ack(envelope)

    def dispose(self) -> None:
        """Tear down the active generation, primarily for shutdown and tests."""
        with self._lock:
            if self._active is not None:
                self._active.dispose()
                self._active = None

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
                f"stale snapshot version {envelope.version}; "
                f"applied version is {active.version}",
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
                dispose=active.dispose,
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
