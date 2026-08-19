"""Hot-reload watch for platform profile and patch files.

Phase P4 of the full-pluginization roadmap, aligned with the dsh
``watchUserPatches`` semantics: file changes trigger a full recompose
through :func:`compose_profile` (so the watcher cannot drift from boot),
a rejected read/parse/composition keeps the last-good snapshot running,
and both outcomes are surfaced as events for the control plane to
broadcast or ACK/NACK.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.plugins import PluginManifest

from .dump_config import load_patch_overlays, load_profile_document
from .profile import (
    ControlPlaneEnvelope,
    ProfileDocument,
    ProfileSnapshot,
    compose_profile,
    control_envelope,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ProfileWatchEvent",
    "ProfileWatcher",
]


@dataclass(frozen=True)
class ProfileWatchEvent:
    """One watcher outcome: applied snapshot or contained rejection."""

    kind: str  # "applied" | "rejected"
    version: int
    digest: str | None
    message: str | None = None


AppliedCallback = Callable[[ControlPlaneEnvelope, ProfileSnapshot], Awaitable[None] | None]
RejectedCallback = Callable[[ProfileWatchEvent], Awaitable[None] | None]


class ProfileWatcher:
    """Poll profile/patch files and recompose on change with last-good semantics."""

    def __init__(
        self,
        profile_path: Path,
        patch_paths: tuple[Path, ...] = (),
        *,
        manifests: Mapping[str, PluginManifest] | None = None,
        on_applied: AppliedCallback | None = None,
        on_rejected: RejectedCallback | None = None,
        interval_seconds: float = 1.0,
        start_version: int = 1,
    ) -> None:
        self._profile_path = profile_path
        self._patch_paths = patch_paths
        self._manifests = manifests
        self._on_applied = on_applied
        self._on_rejected = on_rejected
        self._interval = interval_seconds
        self._version = start_version - 1
        self._fingerprint: tuple[tuple[str, int, int], ...] | None = None
        self._last_good: ProfileSnapshot | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def last_good(self) -> ProfileSnapshot | None:
        """Return the most recent successfully composed snapshot."""
        return self._last_good

    @property
    def version(self) -> int:
        """Return the version of the last applied snapshot."""
        return self._version

    async def start(self) -> None:
        """Start the background watch loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="memstack-profile-watch")

    async def stop(self) -> None:
        """Stop the watch loop and drain the in-flight poll."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def poll_once(self) -> ProfileWatchEvent | None:
        """Poll once; returns the outcome event when something changed.

        The first poll composes silently to establish the last-good
        baseline without emitting, mirroring "boot already applied this
        state". A failed composition is reported as a rejection on any poll.
        """
        fingerprint = self._stat_fingerprint()
        first_poll = self._fingerprint is None
        if not first_poll and fingerprint == self._fingerprint:
            return None
        self._fingerprint = fingerprint
        try:
            snapshot = self._compose()
        except Exception as exc:
            event = ProfileWatchEvent(
                kind="rejected",
                version=self._version,
                digest=self._last_good.digest if self._last_good else None,
                message=str(exc),
            )
            logger.warning("profile watch rejected a change: %s", exc)
            if self._on_rejected is not None:
                await _maybe_await(self._on_rejected(event))
            return event

        self._last_good = snapshot
        if first_poll:
            return None
        self._version += 1
        envelope = control_envelope(snapshot, version=self._version)
        event = ProfileWatchEvent(
            kind="applied",
            version=self._version,
            digest=snapshot.digest,
        )
        if self._on_applied is not None:
            await _maybe_await(self._on_applied(envelope, snapshot))
        return event

    async def _run(self) -> None:
        # The first poll records the baseline fingerprint without emitting,
        # mirroring "boot already applied this state".
        self._fingerprint = self._stat_fingerprint()
        while True:
            await asyncio.sleep(self._interval)
            await self.poll_once()

    def _stat_fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        points: list[tuple[str, int, int]] = []
        for path in (self._profile_path, *self._patch_paths):
            try:
                stat_result = path.stat()
            except OSError:
                points.append((str(path), -1, -1))
                continue
            points.append((str(path), stat_result.st_mtime_ns, stat_result.st_size))
        return tuple(points)

    def _compose(self) -> ProfileSnapshot:
        document = load_profile_document(self._profile_path)
        overlays = load_patch_overlays(self._patch_paths)
        effective = ProfileDocument(
            profile_id=document.profile_id,
            layers=document.layers,
            patches=(*document.patches, *overlays),
        )
        manifests = self._manifests
        if manifests is None:
            from .builtin_manifests import default_builtin_manifests

            manifests = default_builtin_manifests()
        return compose_profile(effective, manifests)


async def _maybe_await(result: object) -> None:
    if inspect.isawaitable(result):
        await result
