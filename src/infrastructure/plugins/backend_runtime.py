"""Backend capability resolution seam (R3).

The reserved backend kinds — ``embedder``, ``reranker``, ``graph_backend``,
``retrieval_backend``, ``workflow_engine``, ``telemetry_exporter`` — resolve
through the process-local capability registry with a builtin fallback,
mirroring the I2 agent-loop seam. When no plugin provides a row the
resolution returns the builtin implementation, so behavior is identical in
both worlds. The trust gate already restricts untrusted plugins to tool
capabilities, so these kinds can only ever be supplied by builtin or signed
(python-trusted) plugins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.model.plugins import CapabilityKind

from .context import CapabilityRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "BACKEND_CAPABILITY_KINDS",
    "BackendResolution",
    "BackendResolutionError",
    "iter_backend_builders",
    "resolve_backend",
    "resolve_telemetry_exporter",
]

#: Capability kinds wired through this seam in R3.
BACKEND_CAPABILITY_KINDS: tuple[CapabilityKind, ...] = (
    CapabilityKind.EMBEDDER,
    CapabilityKind.RERANKER,
    CapabilityKind.GRAPH_BACKEND,
    CapabilityKind.RETRIEVAL_BACKEND,
    CapabilityKind.WORKFLOW_ENGINE,
    CapabilityKind.TELEMETRY_EXPORTER,
)

#: Plugin id used for kernel-shipped builtin implementations.
BUILTIN_PLUGIN_ID = "memstack-kernel"


class BackendResolutionError(RuntimeError):
    """Raised when a backend capability cannot be resolved or is malformed."""


@dataclass(frozen=True)
class BackendResolution:
    """The outcome of one backend capability resolution."""

    kind: CapabilityKind
    capability_id: str
    plugin_id: str
    scope: str  # "plugin" | "builtin"
    implementation: object


def resolve_backend(
    registry: CapabilityRegistry | None,
    kind: CapabilityKind,
    *,
    capability_id: str = "default",
    builtin: object | None = None,
    validator: Callable[[object], None] | None = None,
) -> BackendResolution:
    """Resolve one backend capability, plugin row first, builtin fallback.

    When ``registry`` is None or has no row for ``(kind, capability_id)`` the
    builtin implementation wins and ``scope`` is ``"builtin"``. When neither a
    plugin row nor a builtin exists, ``BackendResolutionError`` is raised —
    callers that legitimately tolerate absence (e.g. the optional workflow
    engine) must catch it or pass a no-op builtin.
    """
    if kind not in BACKEND_CAPABILITY_KINDS:
        raise BackendResolutionError(f"{kind.value} is not a backend capability kind")
    if registry is not None:
        matches = [
            record
            for record in registry.list_capabilities()
            if record.kind == kind and record.capability_id == capability_id
        ]
        if matches:
            # Deterministic choice when several plugins claim the same row.
            record = min(matches, key=lambda item: item.plugin_id)
            if validator is not None:
                validator(record.implementation)
            return BackendResolution(
                kind=kind,
                capability_id=capability_id,
                plugin_id=record.plugin_id,
                scope="plugin",
                implementation=record.implementation,
            )
    if builtin is not None:
        if validator is not None:
            validator(builtin)
        logger.debug(
            "backend %s:%s resolved to builtin default",
            kind.value,
            capability_id,
        )
        return BackendResolution(
            kind=kind,
            capability_id=capability_id,
            plugin_id=BUILTIN_PLUGIN_ID,
            scope="builtin",
            implementation=builtin,
        )
    message = f"no {kind.value} capability registered as {capability_id!r}"
    message += " and no builtin default was supplied"
    raise BackendResolutionError(message)


def iter_backend_builders(
    registry: CapabilityRegistry | None,
    kind: CapabilityKind,
) -> tuple[BackendResolution, ...]:
    """Return plugin rows of one backend kind whose implementation is callable.

    Builder-style backends (graph_backend, retrieval_backend) contribute
    factory builders keyed by capability id (used as the engine type).
    Non-callable rows are skipped with a warning; they never fail factory
    construction. Rows are returned in deterministic plugin-id order.
    """
    if registry is None:
        return ()
    rows: list[BackendResolution] = []
    for record in registry.list_capabilities():
        if record.kind != kind:
            continue
        if not callable(record.implementation):
            logger.warning(
                "backend %s:%s from plugin %s is not callable; skipped",
                kind.value,
                record.capability_id,
                record.plugin_id,
            )
            continue
        rows.append(
            BackendResolution(
                kind=kind,
                capability_id=record.capability_id,
                plugin_id=record.plugin_id,
                scope="plugin",
                implementation=record.implementation,
            )
        )
    rows.sort(key=lambda row: (row.capability_id, row.plugin_id))
    return tuple(rows)


def resolve_telemetry_exporter(registry: CapabilityRegistry | None) -> BackendResolution:
    """Resolve the telemetry exporter, falling back to the noop builtin.

    Telemetry is best-effort by design: when no plugin row is active the
    builtin noop exporter keeps resolution total (R3c).
    """
    from .backend_adapters import NoopTelemetryExporter

    return resolve_backend(
        registry,
        CapabilityKind.TELEMETRY_EXPORTER,
        builtin=NoopTelemetryExporter(),
    )
