"""Generated catalog and dependency preflight for plugin runtime v2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from src.domain.model.plugins.generated_catalog_v2 import (
    PLUGIN_MODULE_CATALOG_DIGEST_V2,
    PLUGIN_MODULE_CATALOG_V2_JSON,
)
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    EventContractV2,
    PluginModuleV2,
    ProfileEntryV2,
    ScopeV2,
)

from .protocol import canonical_json_v2, plugin_contract_digest_v2
from .runtime_context import RuntimeV2Error, scope_contains_v2, scope_rank_v2


@dataclass(frozen=True, kw_only=True)
class ModuleCatalogEntryV2:
    """One immutable target-catalog attestation row used before code loading."""

    plugin_id: str
    plugin_version: str
    module_ref: str
    entrypoint: str
    artifact_source: str
    artifact_digest: str
    targets: tuple[DataPlaneTargetV2, ...]
    contract_digest: str


def generated_contract_digest_v2(
    module_ref: str,
    *,
    target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
) -> str:
    """Return one exact digest from the generated target catalog."""
    entry = generated_target_catalog_v2(target).get(module_ref)
    if entry is None:
        raise RuntimeV2Error(
            "missing_target_catalog",
            f"module {module_ref} is absent from {target.value} catalog",
        )
    return entry.contract_digest


def generated_target_catalog_v2(
    target: DataPlaneTargetV2,
) -> dict[str, ModuleCatalogEntryV2]:
    payload = cast(dict[str, Any], json.loads(PLUGIN_MODULE_CATALOG_V2_JSON))
    embedded_digest = payload.pop("catalog_digest", None)
    expected_digest = f"sha256:{hashlib.sha256(canonical_json_v2(payload)).hexdigest()}"
    if embedded_digest != expected_digest or expected_digest != PLUGIN_MODULE_CATALOG_DIGEST_V2:
        raise RuntimeV2Error(
            "catalog_digest_mismatch",
            "generated plugin module catalog digest is invalid",
        )
    entries: dict[str, ModuleCatalogEntryV2] = {}
    for raw in cast(list[dict[str, Any]], payload["modules"]):
        targets = tuple(DataPlaneTargetV2(value) for value in raw["targets"])
        if target not in targets:
            continue
        entry = ModuleCatalogEntryV2(
            plugin_id=raw["plugin_id"],
            plugin_version=raw["plugin_version"],
            module_ref=raw["module_ref"],
            entrypoint=raw["entrypoint"],
            artifact_source=raw["artifact_source"],
            artifact_digest=raw["artifact_digest"],
            targets=targets,
            contract_digest=raw["contract_digest"],
        )
        if entry.module_ref in entries:
            raise RuntimeV2Error(
                "duplicate_target_catalog_module",
                f"module {entry.module_ref} appears more than once in target catalog",
            )
        entries[entry.module_ref] = entry
    return entries


def validate_contract_digests_v2(
    module: PluginModuleV2,
    *,
    catalog_entry: ModuleCatalogEntryV2,
    plugin_id: str,
    plugin_version: str,
) -> None:
    expected = plugin_contract_digest_v2(module.contract)
    if module.contract_digest != expected:
        raise RuntimeV2Error(
            "contract_digest_mismatch",
            f"module {module.module_ref} contract digest differs from its contract",
        )
    if catalog_entry.contract_digest != expected:
        raise RuntimeV2Error(
            "contract_digest_mismatch",
            f"module {module.module_ref} target catalog digest differs from manifest",
        )
    if module.artifact.digest != catalog_entry.artifact_digest:
        raise RuntimeV2Error(
            "artifact_digest_mismatch",
            f"module {module.module_ref} artifact digest differs from target catalog",
        )
    if module.artifact.source != catalog_entry.artifact_source:
        raise RuntimeV2Error(
            "artifact_source_mismatch",
            f"module {module.module_ref} artifact source differs from target catalog",
        )
    if module.entrypoint != catalog_entry.entrypoint:
        raise RuntimeV2Error(
            "artifact_entrypoint_mismatch",
            f"module {module.module_ref} entrypoint differs from target catalog",
        )
    if (
        module.module_ref != catalog_entry.module_ref
        or plugin_id != catalog_entry.plugin_id
        or plugin_version != catalog_entry.plugin_version
        or len(module.targets) != len(catalog_entry.targets)
        or set(module.targets) != set(catalog_entry.targets)
    ):
        raise RuntimeV2Error(
            "catalog_module_mismatch",
            f"module {module.module_ref} metadata differs from target catalog",
        )


def preflight_entries_v2(
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[str, PluginModuleV2],
) -> None:
    provider_identities: dict[tuple[str, str, ScopeV2, str | None], str] = {}
    for entry_id, entry in entries.items():
        contract = modules[entry_id].contract
        validator = jsonschema.Draft202012Validator(cast(Any, contract.config_schema))
        errors = sorted(
            validator.iter_errors(cast(Any, entry.config)),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            error = errors[0]
            location = ".".join(str(item) for item in error.absolute_path) or "$"
            raise RuntimeV2Error(
                "invalid_module_config",
                f"entry {entry_id} config {location}: {error.message}",
            )

        requirements = {item.alias: item for item in contract.services.requires}
        injected = set(entry.inject)
        required = set(requirements)
        missing = sorted(required - injected)
        if missing:
            raise RuntimeV2Error(
                "missing_required_inject",
                f"entry {entry_id} is missing inject aliases: {', '.join(missing)}",
            )
        unexpected = sorted(injected - required)
        if unexpected:
            raise RuntimeV2Error(
                "unexpected_inject",
                f"entry {entry_id} has unexpected inject aliases: {', '.join(unexpected)}",
            )
        for alias, requirement in requirements.items():
            if entry.inject[alias] != requirement.service:
                raise RuntimeV2Error(
                    "inject_service_mismatch",
                    f"entry {entry_id} alias {alias} must inject {requirement.service}",
                )

        declared_services = {item.service for item in contract.services.provides} | {
            item.service for item in contract.services.requires
        }
        unexpected_isolation = sorted(set(entry.isolate) - declared_services)
        if unexpected_isolation:
            raise RuntimeV2Error(
                "unexpected_isolation",
                f"entry {entry_id} isolates undeclared services: {', '.join(unexpected_isolation)}",
            )

        for provision in contract.services.provides:
            identity = (
                provision.service,
                provision.version,
                entry.scope,
                entry.isolate.get(provision.service),
            )
            owner = provider_identities.get(identity)
            if owner is not None:
                raise RuntimeV2Error(
                    "provider_conflict",
                    f"entries {owner} and {entry_id} provide the same service identity",
                )
            provider_identities[identity] = entry_id


def event_contract_catalog_v2(
    modules: Iterable[PluginModuleV2],
) -> dict[str, EventContractV2]:
    declarations: dict[str, EventContractV2] = {}
    for module in modules:
        for declaration in (*module.contract.events.emits, *module.contract.events.handles):
            previous = declarations.get(declaration.event)
            if previous is not None and previous != declaration:
                raise RuntimeV2Error(
                    "event_contract_mismatch",
                    f"event {declaration.event} has inconsistent contracts",
                )
            declarations[declaration.event] = declaration
    return declarations


def resolve_entry_service_provider_v2(
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[str, PluginModuleV2],
    *,
    entry_id: str,
    service: str,
    version: str,
    scope: ScopeV2,
    isolate: Mapping[str, str],
) -> str:
    """Select the exact nearest provider using runtime injection semantics."""
    providers = [
        provider_id
        for provider_id, module in modules.items()
        if any(
            item.service == service and item.version == version
            for item in module.contract.services.provides
        )
        and scope_contains_v2(entries[provider_id].scope, scope)
        and entries[provider_id].isolate.get(service) == isolate.get(service)
    ]
    if not providers:
        has_other_version = any(
            item.service == service
            and scope_contains_v2(entries[provider_id].scope, scope)
            and entries[provider_id].isolate.get(service) == isolate.get(service)
            for provider_id, module in modules.items()
            for item in module.contract.services.provides
        )
        raise RuntimeV2Error(
            "service_version_mismatch" if has_other_version else "missing_inject_provider",
            f"entry {entry_id} injects missing service {service}@{version}",
        )
    providers.sort(key=lambda item: scope_rank_v2(entries[item].scope), reverse=True)
    top_rank = scope_rank_v2(entries[providers[0]].scope)
    nearest = [item for item in providers if scope_rank_v2(entries[item].scope) == top_rank]
    if len(nearest) != 1:
        raise RuntimeV2Error(
            "ambiguous_inject_provider",
            f"entry {entry_id} has ambiguous service {service}",
        )
    return nearest[0]


def entry_dependencies_v2(
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[str, PluginModuleV2],
    *,
    entry_ids: Iterable[str] | None = None,
) -> dict[str, set[str]]:
    """Resolve dependencies for all entries or an explicitly selected subset."""
    dependencies: dict[str, set[str]] = {}
    for entry_id in entries if entry_ids is None else entry_ids:
        entry = entries[entry_id]
        dependencies[entry_id] = set()
        if entry.parent_entry_id is not None:
            dependencies[entry_id].add(entry.parent_entry_id)
        for requirement in modules[entry_id].contract.services.requires:
            provider = resolve_entry_service_provider_v2(
                entries,
                modules,
                entry_id=entry_id,
                service=requirement.service,
                version=requirement.version,
                scope=entry.scope,
                isolate=entry.isolate,
            )
            if provider != entry_id:
                dependencies[entry_id].add(provider)
    return dependencies


def entry_order_v2(
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[str, PluginModuleV2],
) -> tuple[str, ...]:
    declaration_rank = {entry_id: index for index, entry_id in enumerate(entries)}
    dependencies = entry_dependencies_v2(entries, modules)

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entry_id: str) -> None:
        if entry_id in visited:
            return
        if entry_id in visiting:
            raise RuntimeV2Error("entry_dependency_cycle", f"entry cycle includes {entry_id}")
        visiting.add(entry_id)
        for dependency in sorted(dependencies[entry_id], key=declaration_rank.__getitem__):
            visit(dependency)
        visiting.remove(entry_id)
        visited.add(entry_id)
        ordered.append(entry_id)

    for entry_id in entries:
        visit(entry_id)
    return tuple(ordered)


__all__ = ["ModuleCatalogEntryV2", "generated_contract_digest_v2"]
