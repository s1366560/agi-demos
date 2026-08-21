"""Generated catalog and dependency preflight for plugin runtime v2."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, cast

import jsonschema

from src.domain.model.plugins.generated_catalog_v2 import PLUGIN_MODULE_CATALOG_V2_JSON
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    EventContractV2,
    PluginModuleV2,
    ProfileEntryV2,
    ScopeV2,
)

from .protocol import plugin_contract_digest_v2
from .runtime_context import RuntimeV2Error, scope_contains_v2, scope_rank_v2


def generated_contract_digest_v2(
    module_ref: str,
    *,
    target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
) -> str:
    """Return one exact digest from the generated target catalog."""
    digest = generated_target_catalog_v2(target).get(module_ref)
    if digest is None:
        raise RuntimeV2Error(
            "missing_target_catalog",
            f"module {module_ref} is absent from {target.value} catalog",
        )
    return digest


def generated_target_catalog_v2(target: DataPlaneTargetV2) -> dict[str, str]:
    payload = json.loads(PLUGIN_MODULE_CATALOG_V2_JSON)
    return {
        item["module_ref"]: item["contract_digest"]
        for item in payload["modules"]
        if target.value in item["targets"]
    }


def validate_contract_digests_v2(
    module: PluginModuleV2,
    *,
    catalog_digest: str,
) -> None:
    expected = plugin_contract_digest_v2(module.contract)
    if module.contract_digest != expected:
        raise RuntimeV2Error(
            "contract_digest_mismatch",
            f"module {module.module_ref} contract digest differs from its contract",
        )
    if catalog_digest != expected:
        raise RuntimeV2Error(
            "contract_digest_mismatch",
            f"module {module.module_ref} target catalog digest differs from manifest",
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


def entry_order_v2(
    entries: Mapping[str, ProfileEntryV2],
    modules: Mapping[str, PluginModuleV2],
) -> tuple[str, ...]:
    dependencies: dict[str, set[str]] = {entry_id: set() for entry_id in entries}
    for entry_id, entry in entries.items():
        if entry.parent_entry_id is not None:
            dependencies[entry_id].add(entry.parent_entry_id)
        for requirement in modules[entry_id].contract.services.requires:
            service = requirement.service
            providers = [
                provider_id
                for provider_id, module in modules.items()
                if any(
                    item.service == service and item.version == requirement.version
                    for item in module.contract.services.provides
                )
                and scope_contains_v2(entries[provider_id].scope, entry.scope)
                and entries[provider_id].isolate.get(service) == entry.isolate.get(service)
            ]
            if not providers:
                has_other_version = any(
                    item.service == service
                    and scope_contains_v2(entries[provider_id].scope, entry.scope)
                    and entries[provider_id].isolate.get(service) == entry.isolate.get(service)
                    for provider_id, module in modules.items()
                    for item in module.contract.services.provides
                )
                raise RuntimeV2Error(
                    "service_version_mismatch" if has_other_version else "missing_inject_provider",
                    f"entry {entry_id} injects missing service {service}@{requirement.version}",
                )
            providers.sort(key=lambda item: scope_rank_v2(entries[item].scope), reverse=True)
            top_rank = scope_rank_v2(entries[providers[0]].scope)
            nearest = [item for item in providers if scope_rank_v2(entries[item].scope) == top_rank]
            if len(nearest) != 1:
                raise RuntimeV2Error(
                    "ambiguous_inject_provider",
                    f"entry {entry_id} has ambiguous service {service}",
                )
            if nearest[0] != entry_id:
                dependencies[entry_id].add(nearest[0])

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entry_id: str) -> None:
        if entry_id in visited:
            return
        if entry_id in visiting:
            raise RuntimeV2Error("entry_dependency_cycle", f"entry cycle includes {entry_id}")
        visiting.add(entry_id)
        for dependency in sorted(dependencies[entry_id]):
            visit(dependency)
        visiting.remove(entry_id)
        visited.add(entry_id)
        ordered.append(entry_id)

    for entry_id in sorted(entries):
        visit(entry_id)
    return tuple(ordered)


__all__ = ["generated_contract_digest_v2"]
