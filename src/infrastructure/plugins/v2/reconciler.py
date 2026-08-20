"""Transactional v2 snapshot reconciliation with last-good retention."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ControlPlaneEnvelopeV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    RestartPolicyV2,
    SnapshotApplyReceiptV2,
)

from .protocol import PLUGIN_PROFILE_TYPE_URL_V2
from .runtime import GenerationManagerV2, LoaderV2


class PlatformPluginSnapshotReconcilerV2:
    """Stages every Fiber before atomically publishing a complete generation."""

    def __init__(
        self,
        loader: LoaderV2,
        manager: GenerationManagerV2 | None = None,
    ) -> None:
        self.loader = loader
        self.manager = manager or GenerationManagerV2()
        self._applied_version: int | None = None
        self._applied_digest: str | None = None
        self._lock = asyncio.Lock()

    @property
    def applied_version(self) -> int | None:
        return self._applied_version

    @property
    def applied_digest(self) -> str | None:
        return self._applied_digest

    async def apply(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
    ) -> SnapshotApplyReceiptV2:
        async with self._lock:
            envelope_error = self._validate_envelope(snapshot, envelope)
            if envelope_error is not None:
                return envelope_error
            active_error = self._check_active(envelope)
            if active_error is not None:
                return active_error
            active = self.manager.current
            if active is not None:
                blocked_entries = _process_boundary_changes(active.snapshot, snapshot)
                if blocked_entries:
                    return self._nack(
                        envelope,
                        "process_boundary_required",
                        f"hot update changes process-boundary entries: {', '.join(blocked_entries)}",
                    )
            try:
                staging = await self.loader.stage(snapshot)
            except Exception as exc:
                return self._nack(
                    envelope,
                    "staging_failed",
                    f"snapshot staging failed: {type(exc).__name__}: {exc}",
                )
            await self.manager.publish(staging)
            self._applied_version = envelope.version
            self._applied_digest = envelope.snapshot_digest
            return self._ack(envelope)

    async def close(self) -> None:
        async with self._lock:
            await self.manager.close()
            self._applied_version = None
            self._applied_digest = None

    def _validate_envelope(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
    ) -> SnapshotApplyReceiptV2 | None:
        if envelope.type_url != PLUGIN_PROFILE_TYPE_URL_V2:
            return self._nack(
                envelope,
                "unsupported_type_url",
                f"unsupported snapshot type_url: {envelope.type_url}",
            )
        if envelope.snapshot_digest != snapshot.digest:
            return self._nack(
                envelope,
                "envelope_digest_mismatch",
                "envelope digest does not match snapshot payload",
            )
        return None

    def _check_active(
        self,
        envelope: ControlPlaneEnvelopeV2,
    ) -> SnapshotApplyReceiptV2 | None:
        if self._applied_version is None or self._applied_digest is None:
            return None
        if envelope.version < self._applied_version:
            return self._nack(
                envelope,
                "stale_version",
                f"stale snapshot version {envelope.version}; applied is {self._applied_version}",
            )
        if envelope.version == self._applied_version:
            if envelope.snapshot_digest == self._applied_digest:
                return self._ack(envelope)
            return self._nack(
                envelope,
                "version_digest_conflict",
                f"snapshot digest changed within version {envelope.version}",
            )
        if envelope.snapshot_digest == self._applied_digest:
            self._applied_version = envelope.version
            return self._ack(envelope)
        return None

    def _ack(self, envelope: ControlPlaneEnvelopeV2) -> SnapshotApplyReceiptV2:
        return SnapshotApplyReceiptV2(
            status=ApplyStatusV2.ACK,
            requested_version=envelope.version,
            requested_digest=envelope.snapshot_digest,
            applied_version=envelope.version,
            applied_digest=envelope.snapshot_digest,
            error_code=None,
            error_message=None,
        )

    def _nack(
        self,
        envelope: ControlPlaneEnvelopeV2,
        error_code: str,
        error_message: str,
    ) -> SnapshotApplyReceiptV2:
        return SnapshotApplyReceiptV2(
            status=ApplyStatusV2.NACK,
            requested_version=envelope.version,
            requested_digest=envelope.snapshot_digest,
            applied_version=self._applied_version,
            applied_digest=self._applied_digest,
            error_code=error_code,
            error_message=error_message,
        )


def _process_boundary_changes(
    previous: ProfileSnapshotV2,
    requested: ProfileSnapshotV2,
) -> tuple[str, ...]:
    previous_entries = _enabled_entries(previous)
    requested_entries = _enabled_entries(requested)
    blocked: list[str] = []
    for entry_id in sorted(previous_entries.keys() | requested_entries.keys()):
        before = previous_entries.get(entry_id)
        after = requested_entries.get(entry_id)
        if before == after:
            continue
        policies = {entry.restart_policy for entry in (before, after) if entry is not None}
        if RestartPolicyV2.PROCESS_BOUNDARY in policies:
            blocked.append(entry_id)
    return tuple(blocked)


def _enabled_entries(snapshot: ProfileSnapshotV2) -> Mapping[str, ProfileEntryV2]:
    return {entry.entry_id: entry for entry in snapshot.entries if entry.enabled}


__all__ = ["PlatformPluginSnapshotReconcilerV2"]
