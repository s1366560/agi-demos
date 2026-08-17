"""Scoped agent tool generation service bridging legacy tool caches."""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.domain.model.plugins import PluginGeneration
from src.domain.ports.plugins import ToolDescriptor, ToolImplementation

from .context import PluginScopeContext


class LegacyToolBuildError(RuntimeError):
    """Raised when legacy tool advertisements are ambiguous or malformed."""


@dataclass(frozen=True)
class ToolSetSnapshot:
    """One immutable raw-tool generation plus its canonical identity."""

    generation: PluginGeneration
    scope: PluginScopeContext
    tools: Mapping[str, Any]
    shadow_inventory: Mapping[str, str]


class LegacyToolImplementation:
    """Callable adapter around a legacy AgentTool/ToolInfo object."""

    def __init__(self, tool: object) -> None:
        self._tool = tool

    @property
    def raw_tool(self) -> object:
        """Return the wrapped legacy tool."""
        return self._tool

    async def __call__(
        self,
        arguments: Mapping[str, Any],
        scope: PluginScopeContext,
    ) -> object:
        """Invoke a legacy tool without exposing scope as a tool argument."""
        _ = scope
        execute = getattr(self._tool, "execute", None)
        if execute is None:
            raise TypeError(f"Legacy tool {self._tool!r} has no execute method")
        return await execute(**dict(arguments))


def legacy_tool_descriptor(tool_id: str, tool: object) -> ToolDescriptor:
    """Build a provider-neutral descriptor from a legacy tool object."""
    name = str(getattr(tool, "name", tool_id) or tool_id)
    if name != tool_id:
        raise LegacyToolBuildError(
            f"legacy tool id mismatch: cache key {tool_id}, advertised name {name}"
        )
    description = str(getattr(tool, "description", "") or "")
    parameters = getattr(tool, "parameters", None)
    permission = getattr(tool, "permission", None)
    return ToolDescriptor(
        id=tool_id,
        name=name,
        description=description,
        parameters=dict(parameters) if isinstance(parameters, Mapping) else {},
        permission=str(permission) if permission is not None else None,
    )


class AgentToolSetService:
    """Publish immutable tool generations for scoped agent executions."""

    def __init__(self, *, profile_digest: str = "legacy") -> None:
        self._profile_digest = profile_digest
        self._lock = threading.RLock()
        self._sequence = 0
        self._snapshots: dict[
            tuple[PluginGeneration, tuple[str | None, str | None, str | None]],
            ToolSetSnapshot,
        ] = {}
        self._current: dict[tuple[str | None, str | None, str | None], ToolSetSnapshot] = {}
        self._shadow_inventory: dict[
            tuple[str | None, str | None, str | None], Mapping[str, str]
        ] = {}

    def publish(
        self,
        scope: PluginScopeContext,
        tools: Mapping[str, Any],
        *,
        profile_digest: str | None = None,
    ) -> ToolSetSnapshot:
        """Validate, freeze, and publish one generation for a scope."""
        normalized_tools = dict(tools)
        descriptors = {
            tool_id: legacy_tool_descriptor(tool_id, tool)
            for tool_id, tool in normalized_tools.items()
        }
        inventory = {
            tool_id: f"{descriptor.name}:{descriptor.description}"
            for tool_id, descriptor in descriptors.items()
        }
        with self._lock:
            self._sequence += 1
            digest = profile_digest or self._profile_digest
            generation = PluginGeneration(profile_digest=digest, sequence=self._sequence)
            snapshot = ToolSetSnapshot(
                generation=generation,
                scope=scope,
                tools=copy.deepcopy(normalized_tools),
                shadow_inventory=inventory,
            )
            scope_key = scope.cache_key()
            self._snapshots[(generation, scope_key)] = snapshot
            self._current[scope_key] = snapshot
            for key in list(self._snapshots):
                if key[1] != scope_key:
                    continue
                if key[0].sequence < self._sequence - 2:
                    del self._snapshots[key]
            return snapshot

    def current(self, scope: PluginScopeContext) -> ToolSetSnapshot | None:
        """Return the current generation for a scope."""
        with self._lock:
            snapshot = self._current.get(scope.cache_key())
            if snapshot is None:
                return None
            return ToolSetSnapshot(
                generation=snapshot.generation,
                scope=snapshot.scope,
                tools=copy.deepcopy(snapshot.tools),
                shadow_inventory=snapshot.shadow_inventory,
            )

    def pin(
        self,
        generation: PluginGeneration,
        scope: PluginScopeContext,
    ) -> ToolSetSnapshot | None:
        """Pin one generation for an in-flight execution."""
        with self._lock:
            snapshot = self._snapshots.get((generation, scope.cache_key()))
            if snapshot is None:
                return None
            return ToolSetSnapshot(
                generation=snapshot.generation,
                scope=snapshot.scope,
                tools=copy.deepcopy(snapshot.tools),
                shadow_inventory=snapshot.shadow_inventory,
            )

    def shadow_diff(
        self,
        scope: PluginScopeContext,
        tools: Mapping[str, Any],
    ) -> bool:
        """Return whether candidate inventory differs from the current generation."""
        current = self.current(scope)
        if current is None:
            return False
        candidate = {
            tool_id: f"{descriptor.name}:{descriptor.description}"
            for tool_id, descriptor in (
                (tool_id, legacy_tool_descriptor(tool_id, tool)) for tool_id, tool in tools.items()
            )
        }
        return candidate != current.shadow_inventory

    def implementation(self, tool_id: str, snapshot: ToolSetSnapshot) -> ToolImplementation:
        """Return a callable adapter for one tool in a pinned generation."""
        try:
            tool = snapshot.tools[tool_id]
        except KeyError as exc:
            raise KeyError(tool_id) from exc
        return LegacyToolImplementation(tool)


_global_service = AgentToolSetService()
_global_service_lock = threading.RLock()


def get_agent_tool_set_service() -> AgentToolSetService:
    """Return the process-local scoped tool generation service."""
    with _global_service_lock:
        return _global_service
