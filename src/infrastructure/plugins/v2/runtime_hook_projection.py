"""Strict one-way projection of tenant V1 runtime-hook state into V2 entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import NoReturn

from src.domain.model.agent.config.tenant_agent_config import RuntimeHookConfig
from src.domain.model.plugins.generated_v2 import ProfileEntryV2, ScopeKindV2, ScopeV2

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_RUNTIME_HOOK_EVENTS_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .composer import ProfileDocumentV2
from .sisyphus_runtime import (
    SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
    SISYPHUS_BEFORE_REQUEST_MODULE_V2,
    SISYPHUS_SESSION_START_MODULE_V2,
)
from .workspace_runtime import (
    WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
    WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    WORKSPACE_SESSION_START_MODULE_V2,
)


class RuntimeHookProjectionV2Error(ValueError):
    """Stable rejection raised before a V2 candidate generation is staged."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class _HookProjectionSpecV2:
    plugin_name: str
    module_ref: str
    hook_name: str
    event: str
    hook_family: str
    default_priority: int
    settings: frozenset[str]


_HOOK_SPECS_V2 = (
    _HookProjectionSpecV2(
        plugin_name="sisyphus-runtime",
        module_ref=SISYPHUS_SESSION_START_MODULE_V2,
        hook_name="on_session_start",
        event=AGENT_SESSION_START_EVENT_V2,
        hook_family="mutating",
        default_priority=20,
        settings=frozenset({"startup_reminder"}),
    ),
    _HookProjectionSpecV2(
        plugin_name="sisyphus-runtime",
        module_ref=SISYPHUS_BEFORE_REQUEST_MODULE_V2,
        hook_name="before_response",
        event=AGENT_BEFORE_REQUEST_EVENT_V2,
        hook_family="mutating",
        default_priority=30,
        settings=frozenset({"require_direct_outcome", "response_reminder"}),
    ),
    _HookProjectionSpecV2(
        plugin_name="sisyphus-runtime",
        module_ref=SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
        hook_name="after_tool_execution",
        event=TOOLS_AFTER_EXECUTE_EVENT_V2,
        hook_family="mutating",
        default_priority=40,
        settings=frozenset({"tool_followup_reminder"}),
    ),
    _HookProjectionSpecV2(
        plugin_name="workspace-runtime",
        module_ref=WORKSPACE_SESSION_START_MODULE_V2,
        hook_name="on_session_start",
        event=AGENT_SESSION_START_EVENT_V2,
        hook_family="mutating",
        default_priority=15,
        settings=frozenset(),
    ),
    _HookProjectionSpecV2(
        plugin_name="workspace-runtime",
        module_ref=WORKSPACE_BEFORE_REQUEST_MODULE_V2,
        hook_name="before_response",
        event=AGENT_BEFORE_REQUEST_EVENT_V2,
        hook_family="mutating",
        default_priority=15,
        settings=frozenset(),
    ),
    _HookProjectionSpecV2(
        plugin_name="workspace-runtime",
        module_ref=WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
        hook_name="after_tool_execution",
        event=TOOLS_AFTER_EXECUTE_EVENT_V2,
        hook_family="mutating",
        default_priority=15,
        settings=frozenset(),
    ),
)
_SPEC_BY_V1_KEY_V2 = {(spec.plugin_name, spec.hook_name): spec for spec in _HOOK_SPECS_V2}
_RUNTIME_MODULE_REFS_V2 = tuple(spec.module_ref for spec in _HOOK_SPECS_V2)


def project_tenant_runtime_hooks_v2(
    document: ProfileDocumentV2,
    *,
    tenant_id: str,
    runtime_hooks: Sequence[RuntimeHookConfig],
) -> ProfileDocumentV2:
    """Build one tenant-scoped, digestable V2 profile candidate from persisted V1 rows."""
    normalized_tenant_id = tenant_id.strip()
    if not normalized_tenant_id:
        _fail("invalid_tenant_runtime_hook_projection", "tenant_id cannot be empty")

    entries_by_module = _runtime_entries(document)
    enabled = {
        module_ref: entries_by_module[module_ref].enabled for module_ref in _RUNTIME_MODULE_REFS_V2
    }
    configs = {
        module_ref: dict(entries_by_module[module_ref].config)
        for module_ref in _RUNTIME_MODULE_REFS_V2
    }
    priorities = {(spec.module_ref, spec.event): spec.default_priority for spec in _HOOK_SPECS_V2}
    seen: set[tuple[str, str]] = set()

    for hook in runtime_hooks:
        key = (hook.plugin_name.strip().lower(), hook.hook_name.strip().lower())
        if key in seen:
            _fail("runtime_hook_v1_duplicate_override", f"duplicate runtime hook {key}")
        seen.add(key)
        spec = _SPEC_BY_V1_KEY_V2.get(key)
        if spec is None:
            _fail(
                "runtime_hook_v1_entry_requires_v2_bundle",
                f"runtime hook {key} has no V2 module contract",
            )
        _validate_identity(hook, spec)
        unexpected_settings = sorted(set(hook.settings) - spec.settings)
        if unexpected_settings:
            _fail(
                "runtime_hook_v1_entry_requires_v2_bundle",
                f"runtime hook {key} has unmapped settings: {', '.join(unexpected_settings)}",
            )
        enabled[spec.module_ref] = hook.enabled
        configs[spec.module_ref].update(hook.settings)
        if hook.priority is not None:
            if type(hook.priority) is not int:
                _fail(
                    "runtime_hook_v1_entry_requires_v2_bundle",
                    f"runtime hook {key} priority must be an integer",
                )
            priorities[(spec.module_ref, spec.event)] = hook.priority

    replacements = {
        module_ref: replace(
            entry,
            enabled=enabled[module_ref],
            config=configs[module_ref],
            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=normalized_tenant_id),
        )
        for module_ref, entry in entries_by_module.items()
    }
    module_order = _runtime_module_order(
        document,
        enabled=enabled,
        priorities=priorities,
    )
    return replace(
        document,
        entries=_replace_runtime_entries(document, replacements, module_order),
    )


def _runtime_entries(document: ProfileDocumentV2) -> dict[str, ProfileEntryV2]:
    result: dict[str, ProfileEntryV2] = {}
    for entry in document.entries:
        if entry.module_ref not in _RUNTIME_MODULE_REFS_V2:
            continue
        if entry.module_ref in result:
            _fail(
                "invalid_tenant_runtime_hook_projection",
                f"profile has duplicate module entry {entry.module_ref}",
            )
        result[entry.module_ref] = entry
    missing = [module_ref for module_ref in _RUNTIME_MODULE_REFS_V2 if module_ref not in result]
    if missing:
        _fail(
            "invalid_tenant_runtime_hook_projection",
            f"profile is missing runtime hook modules: {', '.join(missing)}",
        )
    return result


def _validate_identity(hook: RuntimeHookConfig, spec: _HookProjectionSpecV2) -> None:
    key = (spec.plugin_name, spec.hook_name)
    hook_family = (hook.hook_family or spec.hook_family).strip().lower()
    if hook_family != spec.hook_family:
        _fail(
            "runtime_hook_mode_fixed_by_contract",
            f"runtime hook {key} mode is fixed as {spec.hook_family}",
        )
    executor_kind = hook.executor_kind.strip().lower()
    source_ref = (hook.source_ref or "").strip().lower()
    entrypoint = (hook.entrypoint or "").strip()
    if (
        executor_kind != "builtin"
        or (source_ref and source_ref != spec.plugin_name)
        or bool(entrypoint)
    ):
        _fail(
            "runtime_hook_v1_custom_executor_requires_v2_bundle",
            f"runtime hook {key} implementation must be supplied by a V2 bundle",
        )


def _runtime_module_order(
    document: ProfileDocumentV2,
    *,
    enabled: Mapping[str, bool],
    priorities: Mapping[tuple[str, str], int],
) -> tuple[str, ...]:
    base_order = tuple(
        entry.module_ref
        for entry in document.entries
        if entry.module_ref in _RUNTIME_MODULE_REFS_V2
    )
    base_rank = {module_ref: index for index, module_ref in enumerate(base_order)}
    dependencies: dict[str, set[str]] = {module_ref: set() for module_ref in base_order}
    for event in AGENT_RUNTIME_HOOK_EVENTS_V2:
        event_modules = [spec.module_ref for spec in _HOOK_SPECS_V2 if spec.event == event]
        enabled_modules = [module_ref for module_ref in event_modules if enabled[module_ref]]
        enabled_modules.sort(key=lambda item: (-priorities[(item, event)], base_rank[item]))
        for before, after in pairwise(enabled_modules):
            dependencies[after].add(before)

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_ref: str) -> None:
        if module_ref in visited:
            return
        if module_ref in visiting:
            _fail(
                "runtime_hook_priority_order_conflict",
                "per-event runtime hook priorities require conflicting Profile orders",
            )
        visiting.add(module_ref)
        for dependency in sorted(dependencies[module_ref], key=base_rank.__getitem__):
            visit(dependency)
        visiting.remove(module_ref)
        visited.add(module_ref)
        ordered.append(module_ref)

    for module_ref in base_order:
        visit(module_ref)
    return tuple(ordered)


def _replace_runtime_entries(
    document: ProfileDocumentV2,
    replacements: Mapping[str, ProfileEntryV2],
    module_order: Sequence[str],
) -> tuple[ProfileEntryV2, ...]:
    entries = list(document.entries)
    positions = [
        index for index, entry in enumerate(entries) if entry.module_ref in _RUNTIME_MODULE_REFS_V2
    ]
    for position, module_ref in zip(positions, module_order, strict=True):
        entries[position] = replacements[module_ref]
    return tuple(entries)


def _fail(code: str, message: str) -> NoReturn:
    raise RuntimeHookProjectionV2Error(code, message)


__all__ = ["RuntimeHookProjectionV2Error", "project_tenant_runtime_hooks_v2"]
