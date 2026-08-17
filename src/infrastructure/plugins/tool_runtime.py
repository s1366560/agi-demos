"""Scoped, generation-isolated tool set construction."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

from src.domain.model.plugins import PluginGeneration
from src.domain.ports.plugins import ToolDescriptor, ToolImplementation, ToolProvider
from src.infrastructure.plugins.context import PluginScopeContext


class ToolSetBuildError(RuntimeError):
    """Raised when providers expose duplicate or invalid tools."""


@dataclass(frozen=True)
class ToolSetGeneration:
    """One immutable tool set pinned by in-flight executions."""

    generation: PluginGeneration
    scope: PluginScopeContext
    descriptors: Mapping[str, ToolDescriptor]
    providers_by_tool: Mapping[str, ToolProvider]

    async def build(self, tool_id: str) -> ToolImplementation:
        """Build one tool from the pinned provider generation."""
        provider = self.providers_by_tool.get(tool_id)
        if provider is None:
            raise KeyError(tool_id)
        return await provider.build_tool(tool_id, self.scope)

    def descriptor(self, tool_id: str) -> ToolDescriptor:
        """Return one descriptor from this generation."""
        return self.descriptors[tool_id]


class ToolSetBuilder:
    """Build a deterministic tool generation from capability providers."""

    def __init__(self, providers: Mapping[str, ToolProvider]) -> None:
        self._providers = dict(providers)

    async def build(
        self,
        scope: PluginScopeContext,
        generation: PluginGeneration,
    ) -> ToolSetGeneration:
        """Enumerate providers and reject duplicate tool ownership."""
        descriptors: dict[str, ToolDescriptor] = {}
        providers_by_tool: dict[str, ToolProvider] = {}
        errors: list[str] = []

        for provider_id in sorted(self._providers):
            provider = self._providers[provider_id]
            advertised = await provider.list_tools(scope)
            for descriptor in sorted(advertised, key=lambda item: item.id):
                if descriptor.id in descriptors:
                    errors.append(
                        f"tool {descriptor.id} is provided by both "
                        f"{providers_by_tool and _provider_id(providers_by_tool[descriptor.id])} "
                        f"and {provider_id}"
                    )
                    continue
                if not descriptor.id or descriptor.id != descriptor.id.strip():
                    errors.append(f"provider {provider_id} advertised invalid tool id")
                    continue
                descriptors[descriptor.id] = descriptor
                providers_by_tool[descriptor.id] = provider

        if errors:
            raise ToolSetBuildError("; ".join(errors))
        return ToolSetGeneration(
            generation=generation,
            scope=scope,
            descriptors=descriptors,
            providers_by_tool=providers_by_tool,
        )


class ToolGenerationStore:
    """Atomic current-generation cache with pinned older generations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: ToolSetGeneration | None = None
        self._generations: dict[
            tuple[PluginGeneration, tuple[str | None, str | None, str | None]], ToolSetGeneration
        ] = {}

    def publish(self, generation: ToolSetGeneration) -> None:
        """Make a generation current without invalidating pinned snapshots."""
        key = _generation_key(generation)
        with self._lock:
            self._current = generation
            self._generations[key] = generation
            cutoff = generation.generation.sequence - 2
            for old_key in list(self._generations):
                if old_key[0].sequence < cutoff:
                    del self._generations[old_key]

    def current(self) -> ToolSetGeneration | None:
        """Return the currently published generation."""
        with self._lock:
            return self._current

    def pin(
        self, generation: PluginGeneration, scope: PluginScopeContext
    ) -> ToolSetGeneration | None:
        """Pin a generation for one execution boundary."""
        with self._lock:
            return self._generations.get((generation, scope.cache_key()))

    def clear(self) -> None:
        """Clear all generations, primarily for tests."""
        with self._lock:
            self._current = None
            self._generations.clear()


def cache_key(
    profile_digest: str,
    scope: PluginScopeContext,
    generation: PluginGeneration,
) -> tuple[str, tuple[str | None, str | None, str | None], int]:
    """Return the canonical tool cache key."""
    return profile_digest, scope.cache_key(), generation.sequence


def _generation_key(
    generation: ToolSetGeneration,
) -> tuple[PluginGeneration, tuple[str | None, str | None, str | None]]:
    return generation.generation, generation.scope.cache_key()


def _provider_id(provider: ToolProvider) -> str:
    return str(getattr(provider, "provider_id", type(provider).__name__))


@dataclass
class StaticToolProvider:
    """In-memory provider used by builtin assembly and tests."""

    provider_id: str
    advertised: tuple[ToolDescriptor, ...]
    implementations: Mapping[str, ToolImplementation]

    async def list_tools(
        self,
        scope: PluginScopeContext,
    ) -> tuple[ToolDescriptor, ...]:
        """Return deterministic descriptors."""
        _ = scope
        return self.advertised

    async def build_tool(
        self,
        tool_id: str,
        scope: PluginScopeContext,
    ) -> ToolImplementation:
        """Return the configured implementation."""
        _ = scope
        try:
            return self.implementations[tool_id]
        except KeyError as exc:
            raise KeyError(tool_id) from exc


@dataclass
class ToolSelectionPolicy:
    """Deterministic selection facts for a tool generation."""

    included_tags: frozenset[str] = frozenset()
    excluded_tools: frozenset[str] = frozenset()
    max_tools: int | None = None

    def apply(
        self,
        descriptors: Mapping[str, ToolDescriptor],
    ) -> tuple[ToolDescriptor, ...]:
        """Return deterministic selected descriptors."""
        selected = [
            descriptor
            for tool_id, descriptor in sorted(descriptors.items())
            if tool_id not in self.excluded_tools
            and (not self.included_tags or self.included_tags.intersection(_tags(descriptor)))
        ]
        if self.max_tools is not None:
            selected = selected[: self.max_tools]
        return tuple(selected)


def _tags(descriptor: ToolDescriptor) -> set[str]:
    return set(descriptor.tags)


AnyToolSetGeneration = ToolSetGeneration
