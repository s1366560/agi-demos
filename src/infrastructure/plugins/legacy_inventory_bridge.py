"""Mirror legacy agent-plugin inventory into the platform capability kernel.

Phase P0 of the full-pluginization roadmap: the legacy ``AgentPluginRegistry``
(V1) remains the compatibility facade, while the platform
``CapabilityRegistry`` (V2) is the unified ownership inventory. This adapter
projects every V1 registration into V2 capability records so inspection,
snapshots, and profile parity see one merged inventory.

Dispatch behavior is unchanged: mirrored implementations are opaque
``LegacyCapability`` markers, and the legacy registry keeps serving calls.
The bridge only ever unwinds registrations it made itself; kernel-owned
capabilities registered by other paths are never removed.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
    ProvidedCapability,
)
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry

from .compatibility import LegacyCapability
from .context import CapabilityRegistry, PluginContext

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[^a-z0-9._:-]+")
_MAX_ID_LENGTH = 64
_MAX_CONTRACT_LENGTH = 191

# Legacy registry buckets that have no V2 capability kind yet. They are
# reported as diagnostics instead of being silently dropped.
_UNMAPPED_BUCKETS = ("command", "service", "provider")


def _sanitize_token(raw: str, *, fallback: str, max_length: int) -> str:
    """Normalize one identifier to the manifest contract alphabet."""
    token = _TOKEN_PATTERN.sub("-", (raw or "").strip().lower()).strip("-.:")
    if not token or not token[0].isalnum():
        token = fallback
    return token[:max_length]


@dataclass(frozen=True)
class LegacyPluginFacts:
    """Optional manifest facts known about one legacy plugin."""

    source: str | None = None
    version: str | None = None
    tool_names: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()

    @property
    def trust(self) -> PluginTrust:
        """Map the discovery source onto a kernel trust tier."""
        if self.source and self.source.startswith("builtin"):
            return PluginTrust.BUILTIN
        return PluginTrust.SIGNED


@dataclass(frozen=True)
class LegacyInventoryDiagnostic:
    """One non-fatal bridge observation."""

    plugin_id: str
    code: str
    message: str


@dataclass(frozen=True)
class LegacyInventorySyncReceipt:
    """Outcome of one bridge synchronization pass."""

    mirrored_plugins: tuple[str, ...]
    mirrored_capabilities: int
    diagnostics: tuple[LegacyInventoryDiagnostic, ...]


@dataclass(frozen=True)
class _DesiredCapability:
    kind: CapabilityKind
    capability_id: str
    contract: str


@dataclass
class _PluginGeneration:
    """One mirrored generation retained for last-good rollback."""

    manifest: PluginManifest
    capabilities: tuple[_DesiredCapability, ...]
    context: PluginContext


class _InventoryCollector:
    """Accumulate desired V2 capabilities from the legacy registry."""

    def __init__(self, facts: Mapping[str, LegacyPluginFacts]) -> None:
        self._facts = facts
        self.desired: dict[str, list[_DesiredCapability]] = {}

    def add(self, plugin_id: str, kind: CapabilityKind, raw_id: str, contract_hint: str) -> None:
        capability_id = _sanitize_token(raw_id, fallback="item", max_length=_MAX_ID_LENGTH)
        contract = _sanitize_token(
            contract_hint,
            fallback=f"{kind.value}:{capability_id}",
            max_length=_MAX_CONTRACT_LENGTH,
        )
        self.desired.setdefault(plugin_id, []).append(
            _DesiredCapability(kind=kind, capability_id=capability_id, contract=contract)
        )

    def facts_for(self, plugin_name: str) -> LegacyPluginFacts:
        """Return declared facts for one plugin, defaults when absent."""
        return self._facts.get(plugin_name, LegacyPluginFacts())


def _collect_tool_capabilities(
    legacy_registry: AgentPluginRegistry,
    collector: _InventoryCollector,
) -> None:
    for plugin_name in legacy_registry.list_tool_factories():
        tool_names = collector.facts_for(plugin_name).tool_names
        if tool_names:
            for tool_name in tool_names:
                collector.add(plugin_name, CapabilityKind.TOOL, tool_name, f"tool:{tool_name}")
        else:
            collector.add(
                plugin_name,
                CapabilityKind.TOOL,
                "tool-factory",
                f"tool-factory:{plugin_name}",
            )
    for plugin_name in legacy_registry.list_sandbox_tool_factories():
        collector.add(
            plugin_name,
            CapabilityKind.TOOL,
            "sandbox-tool-factory",
            f"sandbox-tool-factory:{plugin_name}",
        )


def _collect_skill_capabilities(
    legacy_registry: AgentPluginRegistry,
    collector: _InventoryCollector,
) -> None:
    for plugin_name in legacy_registry.list_skill_factories():
        skill_ids = collector.facts_for(plugin_name).skill_ids
        if skill_ids:
            for skill_id in skill_ids:
                collector.add(
                    plugin_name, CapabilityKind.SKILL_PROVIDER, skill_id, f"skill:{skill_id}"
                )
        else:
            collector.add(
                plugin_name,
                CapabilityKind.SKILL_PROVIDER,
                "skill-factory",
                f"skill-factory:{plugin_name}",
            )


def _collect_hook_capabilities(
    legacy_registry: AgentPluginRegistry,
    collector: _InventoryCollector,
) -> None:
    # Hooks are keyed by hook name first, then plugin.
    for hook_name, handlers in legacy_registry.list_hooks().items():
        for plugin_name in handlers:
            collector.add(plugin_name, CapabilityKind.HOOK, hook_name, f"hook:{hook_name}")
    for event_name, lifecycle_handlers in legacy_registry.list_lifecycle_hooks().items():
        for plugin_name in lifecycle_handlers:
            collector.add(
                plugin_name,
                CapabilityKind.HOOK,
                f"lifecycle-{event_name}",
                f"lifecycle:{event_name}",
            )


def _collect_surface_capabilities(
    legacy_registry: AgentPluginRegistry,
    collector: _InventoryCollector,
) -> None:
    for channel_type, (owner, _factory) in legacy_registry.list_channel_adapter_factories().items():
        collector.add(owner, CapabilityKind.CHANNEL, channel_type, f"channel:{channel_type}")
    for plugin_name, routes in legacy_registry.list_http_routes().items():
        for route in routes:
            route_id = f"{route.method.lower()}{route.path}"
            collector.add(
                plugin_name,
                CapabilityKind.HTTP_ROUTE,
                route_id,
                f"http-{route_id}",
            )
    for plugin_name, commands in legacy_registry.list_cli_commands().items():
        for command in commands:
            collector.add(
                plugin_name, CapabilityKind.CLI_COMMAND, command.name, f"cli:{command.name}"
            )
    for plugin_name in _list_subagent_resolver_plugins(legacy_registry):
        collector.add(
            plugin_name,
            CapabilityKind.SUBAGENT_PROVIDER,
            "subagent-resolver",
            f"subagent-resolver:{plugin_name}",
        )


def _collect_legacy_inventory(
    legacy_registry: AgentPluginRegistry,
    facts: Mapping[str, LegacyPluginFacts],
) -> tuple[dict[str, list[_DesiredCapability]], list[LegacyInventoryDiagnostic]]:
    """Project the legacy registry inventory into desired V2 capabilities."""
    collector = _InventoryCollector(facts)
    _collect_tool_capabilities(legacy_registry, collector)
    _collect_skill_capabilities(legacy_registry, collector)
    _collect_hook_capabilities(legacy_registry, collector)
    _collect_surface_capabilities(legacy_registry, collector)

    diagnostics: list[LegacyInventoryDiagnostic] = []
    for bucket in _UNMAPPED_BUCKETS:
        for plugin_name in _list_unmapped_bucket(legacy_registry, bucket):
            diagnostics.append(
                LegacyInventoryDiagnostic(
                    plugin_id=plugin_name,
                    code="unmapped_legacy_capability",
                    message=(
                        f"legacy {bucket} registrations have no V2 capability kind; "
                        "they stay dispatch-only in the V1 facade"
                    ),
                )
            )

    return collector.desired, diagnostics


def _list_subagent_resolver_plugins(legacy_registry: AgentPluginRegistry) -> tuple[str, ...]:
    """Return plugin names that registered sub-agent resolver factories."""
    list_method = getattr(legacy_registry, "list_subagent_resolver_factories", None)
    if not callable(list_method):
        return ()
    factories = cast("Mapping[str, object]", list_method())
    return tuple(factories)


def _list_unmapped_bucket(
    legacy_registry: AgentPluginRegistry,
    bucket: str,
) -> tuple[str, ...]:
    """Return plugin names owning legacy buckets without a V2 kind."""
    if bucket == "command":
        return tuple(owner for owner, _ in legacy_registry.list_commands().values())
    if bucket == "service":
        return tuple(owner for owner, _ in legacy_registry.list_services().values())
    if bucket == "provider":
        return tuple(owner for owner, _ in legacy_registry.list_providers().values())
    return ()


def _dedupe_capabilities(
    plugin_id: str,
    capabilities: list[_DesiredCapability],
    diagnostics: list[LegacyInventoryDiagnostic],
) -> tuple[_DesiredCapability, ...]:
    """Drop duplicate capability keys and contracts, keeping the first entry."""
    seen_keys: set[tuple[str, str]] = set()
    seen_contracts: set[str] = set()
    deduped: list[_DesiredCapability] = []
    for capability in capabilities:
        key = (capability.kind.value, capability.capability_id)
        if key in seen_keys or capability.contract in seen_contracts:
            diagnostics.append(
                LegacyInventoryDiagnostic(
                    plugin_id=plugin_id,
                    code="duplicate_capability",
                    message=(
                        f"duplicate {key[0]}:{key[1]} or contract "
                        f"{capability.contract} collapsed to first registration"
                    ),
                )
            )
            continue
        seen_keys.add(key)
        seen_contracts.add(capability.contract)
        deduped.append(capability)
    return tuple(deduped)


def _build_manifest(
    plugin_id: str,
    capabilities: tuple[_DesiredCapability, ...],
    plugin_facts: LegacyPluginFacts,
) -> PluginManifest:
    """Synthesize the V2 manifest for one legacy plugin generation."""
    return PluginManifest(
        schema_version=1,
        id=plugin_id,
        version=plugin_facts.version or "0.0.0",
        runtime=PluginRuntimeKind.PYTHON_TRUSTED,
        trust=plugin_facts.trust,
        provides=tuple(
            ProvidedCapability(
                kind=capability.kind,
                id=capability.capability_id,
                contract=capability.contract,
            )
            for capability in capabilities
        ),
    )


@dataclass
class LegacyInventoryBridge:
    """Reversible adapter from the V1 registry to the V2 capability kernel."""

    legacy_registry: AgentPluginRegistry
    capability_registry: CapabilityRegistry
    _generations: dict[str, _PluginGeneration] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def sync(
        self,
        *,
        facts: Mapping[str, LegacyPluginFacts] | None = None,
    ) -> LegacyInventorySyncReceipt:
        """Reconcile the mirrored inventory with the legacy registry state.

        Per plugin the bridge closes only its own previous generation, then
        registers the desired generation. Capabilities that would collide with
        a foreign (kernel-owned) record are skipped with a diagnostic, and any
        unexpected activation failure restores the previous generation.
        """
        resolved_facts = dict(facts or {})
        desired_by_plugin, diagnostics = _collect_legacy_inventory(
            self.legacy_registry,
            resolved_facts,
        )

        with self._lock:
            mirrored: list[str] = []
            capability_count = 0

            stale_plugins = sorted(set(self._generations) - set(desired_by_plugin))
            for plugin_id in stale_plugins:
                self._generations.pop(plugin_id).context.close()
                diagnostics.append(
                    LegacyInventoryDiagnostic(
                        plugin_id=plugin_id,
                        code="mirror_removed",
                        message="legacy plugin no longer registered; mirrored inventory removed",
                    )
                )

            for plugin_id in sorted(desired_by_plugin):
                capabilities = _dedupe_capabilities(
                    plugin_id,
                    desired_by_plugin[plugin_id],
                    diagnostics,
                )
                capabilities = self._drop_foreign_conflicts(
                    plugin_id,
                    capabilities,
                    diagnostics,
                )
                if not capabilities:
                    previous = self._generations.pop(plugin_id, None)
                    if previous is not None:
                        previous.context.close()
                    continue
                capability_count += self._activate(plugin_id, capabilities, resolved_facts)
                mirrored.append(plugin_id)

            return LegacyInventorySyncReceipt(
                mirrored_plugins=tuple(mirrored),
                mirrored_capabilities=capability_count,
                diagnostics=tuple(diagnostics),
            )

    def unregister_plugin(self, plugin_id: str) -> bool:
        """Remove the mirrored generation of one plugin, if present."""
        with self._lock:
            generation = self._generations.pop(plugin_id, None)
            if generation is None:
                return False
            generation.context.close()
            return True

    def close(self) -> None:
        """Tear down every mirrored registration in reverse plugin order."""
        with self._lock:
            for plugin_id in sorted(self._generations, reverse=True):
                self._generations[plugin_id].context.close()
            self._generations.clear()

    def _drop_foreign_conflicts(
        self,
        plugin_id: str,
        capabilities: tuple[_DesiredCapability, ...],
        diagnostics: list[LegacyInventoryDiagnostic],
    ) -> tuple[_DesiredCapability, ...]:
        """Skip capabilities already owned outside this bridge."""
        generation = self._generations.get(plugin_id)
        owned_keys: set[tuple[str, str]] = (
            {(item.kind.value, item.capability_id) for item in generation.capabilities}
            if generation is not None
            else set()
        )
        kept: list[_DesiredCapability] = []
        for capability in capabilities:
            key = (capability.kind.value, capability.capability_id)
            existing = self.capability_registry.get(
                capability.kind,
                capability.capability_id,
                plugin_id=plugin_id,
            )
            if existing is not None and key not in owned_keys:
                diagnostics.append(
                    LegacyInventoryDiagnostic(
                        plugin_id=plugin_id,
                        code="foreign_capability_conflict",
                        message=(
                            f"{key[0]}:{key[1]} is owned outside the legacy bridge; "
                            "mirrored registration skipped"
                        ),
                    )
                )
                continue
            kept.append(capability)
        return tuple(kept)

    def _activate(
        self,
        plugin_id: str,
        capabilities: tuple[_DesiredCapability, ...],
        facts: Mapping[str, LegacyPluginFacts],
    ) -> int:
        """Swap one plugin generation with last-good rollback."""
        manifest = _build_manifest(
            plugin_id,
            capabilities,
            facts.get(plugin_id, LegacyPluginFacts()),
        )
        previous = self._generations.pop(plugin_id, None)
        if previous is not None:
            previous.context.close()

        context = PluginContext(self.capability_registry, manifest)
        try:
            for capability in capabilities:
                _ = context.register_capability(
                    capability.kind,
                    capability.capability_id,
                    LegacyCapability(plugin_id=plugin_id, capability=capability.contract),
                )
        except Exception:
            context.close()
            if previous is not None:
                self._restore_previous(plugin_id, previous)
            raise

        self._generations[plugin_id] = _PluginGeneration(
            manifest=manifest,
            capabilities=capabilities,
            context=context,
        )
        return len(capabilities)

    def _restore_previous(self, plugin_id: str, previous: _PluginGeneration) -> None:
        """Rebuild the last-good generation after an unexpected failure."""
        context = PluginContext(self.capability_registry, previous.manifest)
        try:
            for capability in previous.capabilities:
                _ = context.register_capability(
                    capability.kind,
                    capability.capability_id,
                    LegacyCapability(plugin_id=plugin_id, capability=capability.contract),
                )
        except Exception:  # pragma: no cover - defensive; restore is best-effort
            context.close()
            logger.exception("legacy bridge last-good restore failed for %s", plugin_id)
            return
        self._generations[plugin_id] = _PluginGeneration(
            manifest=previous.manifest,
            capabilities=previous.capabilities,
            context=context,
        )


__all__ = [
    "LegacyInventoryBridge",
    "LegacyInventoryDiagnostic",
    "LegacyInventorySyncReceipt",
    "LegacyPluginFacts",
]
