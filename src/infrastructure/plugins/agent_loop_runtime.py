"""Per-turn agent loop resolution for the pluggable loop seam.

Phase P2 of the full-pluginization roadmap: ``SessionProcessor`` becomes the
default ``agent_loop`` capability, and the loop is resolved fresh for every
turn by ``(provider, model)`` — never pinned for a whole session (mirrors
ADR-0008 on the Rust side). Selection order: model-scoped capability, then
provider-scoped, then ``auto`` (highest ``supports()`` priority), then the
builtin default. Resolution therefore always succeeds with a defined scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from src.domain.model.plugins import CapabilityKind

from .context import CapabilityRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "AgentLoopDriver",
    "AgentLoopResolutionError",
    "AgentLoopResolver",
    "AgentLoopSelection",
    "validate_loop_implementation",
]


class AgentLoopDriver(Protocol):
    """Structural contract every agent loop capability must satisfy."""

    async def run(self, context: Any) -> Any:  # noqa: ANN401
        """Execute one prepared turn and return its outcome."""
        ...


class AgentLoopResolutionError(RuntimeError):
    """Raised for malformed resolution inputs or non-conforming loops."""


@dataclass(frozen=True)
class AgentLoopSelection:
    """The outcome of one per-turn loop resolution."""

    loop_id: str
    plugin_id: str
    scope: str  # "model" | "provider" | "auto" | "builtin"
    implementation: object


@dataclass(frozen=True)
class _Candidate:
    plugin_id: str
    capability_id: str
    implementation: object


def validate_loop_implementation(implementation: object) -> None:
    """Assert the structural loop contract (callable ``run``)."""
    run = getattr(implementation, "run", None)
    if not callable(run):
        raise AgentLoopResolutionError(
            f"agent loop implementation {type(implementation).__name__} has no callable run"
        )


class AgentLoopResolver:
    """Resolve the agent loop for one ``(provider, model)`` pair per turn."""

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        *,
        builtin_loop: object | None = None,
    ) -> None:
        self._registry = capability_registry
        self._builtin_loop = builtin_loop

    def resolve(self, provider_id: str, model_id: str) -> AgentLoopSelection:
        """Resolve the loop for one turn; never pins across turns."""
        if not provider_id.strip() or not model_id.strip():
            raise AgentLoopResolutionError("provider_id and model_id must be non-empty")

        model_scoped = self._lookup(f"{provider_id}:{model_id}")
        if model_scoped is not None:
            return self._select(model_scoped, "model")

        provider_scoped = self._lookup(provider_id)
        if provider_scoped is not None:
            return self._select(provider_scoped, "provider")

        auto = self._select_auto(provider_id, model_id)
        if auto is not None:
            return auto

        return self._builtin(provider_id, model_id)

    def _lookup(self, capability_id: str) -> _Candidate | None:
        for record in self._registry.list_capabilities():
            if record.kind != CapabilityKind.AGENT_LOOP:
                continue
            if record.capability_id != capability_id:
                continue
            return _Candidate(
                plugin_id=record.plugin_id,
                capability_id=record.capability_id,
                implementation=record.implementation,
            )
        return None

    def _select(self, candidate: _Candidate, scope: str) -> AgentLoopSelection:
        validate_loop_implementation(candidate.implementation)
        return AgentLoopSelection(
            loop_id=candidate.capability_id,
            plugin_id=candidate.plugin_id,
            scope=scope,
            implementation=candidate.implementation,
        )

    def _select_auto(self, provider_id: str, model_id: str) -> AgentLoopSelection | None:
        context = {"provider_id": provider_id, "model_id": model_id}
        best: tuple[int, str, str, object] | None = None
        for record in self._registry.list_capabilities():
            if record.kind != CapabilityKind.AGENT_LOOP:
                continue
            supports = getattr(record.implementation, "supports", None)
            if not callable(supports):
                continue
            priority = supports(context)
            if priority is None or isinstance(priority, bool) or not isinstance(
                priority, (int, float)
            ):
                continue
            key = (
                int(priority),
                record.plugin_id,
                record.capability_id,
                record.implementation,
            )
            if best is None or key[:3] > best[:3]:
                best = key
        if best is None:
            return None
        _priority, plugin_id, capability_id, implementation = best
        validate_loop_implementation(implementation)
        return AgentLoopSelection(
            loop_id=capability_id,
            plugin_id=plugin_id,
            scope="auto",
            implementation=implementation,
        )

    def _builtin(self, provider_id: str, model_id: str) -> AgentLoopSelection:
        default = self._lookup("default")
        if default is not None:
            return self._select(default, "builtin")
        if self._builtin_loop is not None:
            builtin = self._builtin_loop
            validate_loop_implementation(builtin)
            logger.debug(
                "agent loop resolved to builtin default for %s/%s",
                provider_id,
                model_id,
            )
            return AgentLoopSelection(
                loop_id="builtin-default",
                plugin_id="memstack-kernel",
                scope="builtin",
                implementation=builtin,
            )
        raise AgentLoopResolutionError(
            f"no agent_loop capability resolves for {provider_id}/{model_id} "
            "and no builtin default is registered"
        )
