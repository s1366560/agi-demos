"""Admit a closed publisher archive to the project business runtime."""

import json
from dataclasses import replace
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.jsonschema import DRAFT202012

from src.domain.model.plugins.chat_adapter_scope import CHAT_ADAPTER_GRANTS
from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    DataPlaneTargetV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    QuotaV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    ServiceRequiredV2,
    TrustKindV2,
)
from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path
from src.infrastructure.plugins.v2.bundle_archive import (
    BundleArchiveV2Error,
    VerifiedBundleArchiveV2,
    declared_bundle_permissions_v2,
    parse_bundle_archive_v2,
)
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import SUPPORTED_SCHEMA_VERSION
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
    TenantBindingV2,
    declared_permissions,
    load_contribution_v2,
)

ensure_plugin_sdk_path()

if TYPE_CHECKING:
    from memstack_plugin_sdk.contract import ContributionDocument
    from memstack_plugin_sdk.package_services import ProjectServices

    from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSpec


def admit_package(
    raw: bytes, keys: tuple[str, ...], approved: frozenset[str], binding: TenantBindingV2 | None
) -> SignedPackageBytesV2:
    if not isinstance(binding, ScopeBindingV2):
        return _verify_package(raw, keys, approved, binding)
    signed_permissions = declared_bundle_permissions_v2(raw)
    package = _verify_package(raw, keys, signed_permissions, binding)
    source = package.contribution
    commands = tuple(command for command in source.commands if command.scope != "tenant")
    pages = tuple(page for page in source.pages if page.scope == "project")
    project = replace(source, commands=commands, pages=pages)
    exclusively_tenant = frozenset(
        permission
        for command in source.commands
        if command.scope == "tenant"
        for permission in command.permissions
    ) - declared_permissions(project)
    # Device permissions belong to the nested signed target, even if a tenant command
    # also names one. Only application operation names may be scoped out at this boundary.
    removable = exclusively_tenant & {
        command.host_operation for command in source.commands if command.host_operation
    }
    missing = signed_permissions - removable - approved
    if missing:
        raise BundleArchiveV2Error(
            "bundle_permission_not_approved",
            f"project package lacks approval for {', '.join(sorted(missing))}",
        )
    return replace(
        package, contribution=project, approved_permissions=package.approved_permissions - removable
    )


def _verify_package(
    raw: bytes, keys: tuple[str, ...], approved: frozenset[str], binding: TenantBindingV2 | None
) -> SignedPackageBytesV2:
    from memstack_plugin_sdk.compatibility import DESCRIPTOR, require_compatible
    from memstack_plugin_sdk.rich_pages import validate_device_tools

    archive = parse_bundle_archive_v2(
        raw,
        source="project-import",
        trusted_public_keys=keys,
        approved_permissions=approved,
        require_signature=True,
    )
    bundle = archive.manifest
    if len(bundle.manifests) != 1:
        raise OptionalBusinessError("invalid_package", "expected one business plugin")
    plugin = bundle.manifests[0]
    if (
        plugin.runtime not in {RuntimeKindV2.WASM, RuntimeKindV2.MCP}
        or plugin.trust != TrustKindV2.SIGNED
        or len(plugin.modules) != 1
        or plugin.plugin_id != bundle.bundle_id
        or plugin.version != bundle.version
    ):
        raise OptionalBusinessError("invalid_package", "unsupported project business contract")
    module = plugin.modules[0]
    if module.targets != (DataPlaneTargetV2.PYTHON,):
        raise OptionalBusinessError("invalid_package", "expected a cloud invoke module")
    artifacts = {a.path: archive.artifacts[a.artifact_id] for a in bundle.artifacts}
    kind = json.loads(artifacts.get("release-kind.json", b'{"kind":"business"}'))
    if kind not in ({"kind": "business"}, {"kind": "adapter"}):
        raise OptionalBusinessError("invalid_package", "invalid release kind")
    targets, device_tool, device_permissions = _device_target(artifacts, plugin, keys, approved)
    require_compatible(artifacts.get(DESCRIPTOR))
    wasm, worker = _executable(archive, plugin, module, artifacts, binding)
    if "contributions.json" not in artifacts:
        raise OptionalBusinessError("invalid_package", "missing signed contribution document")
    contribution = load_contribution_v2(json.loads(artifacts["contributions.json"]))
    # The executor uses an offline registry. Validate schemas before staging a release.
    services = _check_host_contract(plugin, module, contribution)
    _check_contributions(contribution, module.entrypoint)
    validate_device_tools(contribution.pages, device_tool)
    files = _ui_files(contribution, artifacts)
    entry = _bound_entry(bundle, plugin, binding)
    granted = _package_grants(plugin, entry, approved, contribution, device_permissions)
    if not device_permissions <= granted:
        raise OptionalBusinessError("forbidden", "device host capability requires approval")
    _check_loop_driver(granted, contribution, worker is not None)
    if chat_grants := granted.intersection(CHAT_ADAPTER_GRANTS):
        permissions = chat_grants | {"tools.execute"}
        if (
            len(chat_grants) != 1
            or granted != permissions
            or worker
            or len(contribution.tools) != 1
            or contribution.tools[0].name != "adapt_chat"
            or contribution.tools[0].permissions != permissions
            or contribution.storage
            or contribution.skills
            or contribution.subagents
            or contribution.commands
        ):
            raise OptionalBusinessError(
                "invalid_package", "chat adaptation requires one dedicated pure Wasm tool"
            )
    return SignedPackageBytesV2(
        plugin_id=plugin.plugin_id,
        kind=kind["kind"],
        targets=targets,
        version=plugin.version,
        digest=bundle.digest,
        wasm=wasm,
        worker=worker,
        services=services,
        contribution=contribution,
        ui_files=files,
        approved_permissions=granted,
        quotas=_quotas(plugin.quotas, entry.quotas, worker=worker is not None),
        entrypoint=module.entrypoint,
        storage_limit=min(
            v
            for v in (
                plugin.quotas.max_storage_bytes,
                entry.quotas.max_storage_bytes,
                16 * 1024 * 1024,
            )
            if v is not None
        ),
    )


def _device_target(
    artifacts: dict[str, bytes],
    plugin: PluginManifestV2,
    keys: tuple[str, ...],
    approved: frozenset[str],
) -> tuple[tuple[str, ...], object, frozenset[str]]:
    from memstack_plugin_sdk.device_capability import (
        DESCRIPTOR as DEVICE_DESCRIPTOR,
        LOCAL_CHAT,
        device_capability_tool,
    )
    from memstack_plugin_sdk.project_http import is_route_permission, is_workspace_permission

    device_permissions: frozenset[str] = frozenset()
    targets: tuple[str, ...] = ("python",)
    device_tool: object = None
    device_bytes = artifacts.get("targets/desktop-sidecar.mspkg")
    if device_bytes is not None:
        native = parse_bundle_archive_v2(
            device_bytes,
            source="device-target",
            trusted_public_keys=keys,
            approved_permissions=frozenset(
                p
                for p in plugin.permissions
                if p in approved
                and (p == "tools.execute" or is_route_permission(p) or is_workspace_permission(p))
            ),
            require_signature=True,
        ).manifest
        if (
            native.bundle_id != plugin.plugin_id
            or native.version != plugin.version
            or len(native.manifests) != 1
            or native.manifests[0].plugin_id != native.bundle_id
            or native.manifests[0].version != native.version
            or native.manifests[0].runtime != RuntimeKindV2.WASM
            or len(native.manifests[0].modules) != 1
            or native.manifests[0].modules[0].targets != (DataPlaneTargetV2.DESKTOP_SIDECAR,)
        ):
            raise OptionalBusinessError("invalid_package", "invalid device release target")
        if len(native.layers) != 1 or len(native.layers[0].entries) != 1:
            raise OptionalBusinessError("invalid_package", "expected one device module entry")
        native_entry = native.layers[0].entries[0]
        device_permissions = frozenset(
            p
            for p in native.manifests[0].permissions
            if is_route_permission(p) or is_workspace_permission(p)
        )
        if not device_permissions <= frozenset(native_entry.permissions):
            raise OptionalBusinessError("forbidden", "device route lacks an executable entry grant")
        device_tool = native_entry.config.get("tool_name")
        targets = ("python", "desktop-sidecar")
    if (descriptor := artifacts.get(DEVICE_DESCRIPTOR)) is not None:
        if device_bytes is not None or LOCAL_CHAT not in plugin.permissions:
            raise OptionalBusinessError(
                "invalid_package", "conflicting or unapproved device capability"
            )
        device_tool = device_capability_tool(descriptor)
        device_permissions = frozenset({LOCAL_CHAT})
        targets = ("python", "desktop-sidecar")
    return targets, device_tool, device_permissions


def _package_grants(
    plugin: PluginManifestV2,
    entry: ProfileEntryV2,
    approved: frozenset[str],
    contribution: "ContributionDocument",
    device_permissions: frozenset[str] = frozenset(),
) -> frozenset[str]:
    from memstack_plugin_sdk.contract import PERMISSIONS

    named = {command.host_operation for command in contribution.commands if command.host_operation}
    named.update(device_permissions)
    if not set(plugin.permissions) <= PERMISSIONS | named:
        raise OptionalBusinessError("invalid_package", "unsupported package permission")
    granted = frozenset(plugin.permissions) & frozenset(entry.permissions) & approved
    if not declared_permissions(contribution) <= granted:
        raise OptionalBusinessError(
            "forbidden", "a contribution lacks a signed and approved permission"
        )
    return granted


def _check_loop_driver(
    granted: frozenset[str], contribution: "ContributionDocument", isolated_worker: bool
) -> None:
    if "agent.loop.drive" in granted:
        drivers = [tool for tool in contribution.tools if "agent.loop.drive" in tool.permissions]
        if not isolated_worker or len(drivers) != 1 or drivers[0].name != "react_loop":
            raise OptionalBusinessError("invalid_package", "expected one isolated ReAct driver")


def _check_host_contract(
    plugin: PluginManifestV2, module: PluginModuleV2, contribution: "ContributionDocument"
) -> "ProjectServices":
    from memstack_plugin_sdk.package_services import project_services

    contract = module.contract
    catalog = ServiceRequiredV2(
        alias="catalog", service="service:tool-set-catalog", version="1.0.0", contributes=True
    )
    requirements = contract.services.requires
    if requirements.count(catalog) != 1 or any(
        row.contributes is not False for row in requirements if row != catalog
    ):
        raise OptionalBusinessError(
            "invalid_package", "unsupported host service or dependency version"
        )
    if contract.events.emits or contract.events.handles:
        raise OptionalBusinessError("invalid_package", "this execution host has no event binding")
    try:
        return project_services(
            {
                "provides": [
                    {"service": row.service, "version": row.version}
                    for row in contract.services.provides
                ],
                "requires": [
                    {"alias": row.alias, "service": row.service, "version": row.version}
                    for row in requirements
                    if row != catalog
                ],
            },
            plugin=plugin.plugin_id,
            target="python",
            worker=plugin.runtime == RuntimeKindV2.MCP,
            tools=contribution.tools,
        )
    except ValueError as exc:
        raise OptionalBusinessError("invalid_package", str(exc)) from exc


def _check_contributions(contribution: "ContributionDocument", entrypoint: str) -> None:
    if contribution.storage and contribution.storage.schema_version > SUPPORTED_SCHEMA_VERSION:
        raise OptionalBusinessError("invalid_package", "unsupported namespace storage schema")
    if any("skills.register" not in skill.permissions for skill in contribution.skills):
        raise OptionalBusinessError("invalid_package", "skill is missing registration permission")
    names = {tool.name for tool in contribution.tools}
    if not names or len(names) != len(contribution.tools):
        raise OptionalBusinessError("invalid_package", "expected unique signed tools")
    if len({c.command_id for c in contribution.commands}) != len(contribution.commands) or any(
        c.host_operation is None and c.tool not in names for c in contribution.commands
    ):
        raise OptionalBusinessError("invalid_package", "commands must bind one declared tool")
    for tool in contribution.tools:
        if tool.abi != entrypoint or "tools.execute" not in tool.permissions:
            raise OptionalBusinessError(
                "invalid_package", "tool ABI differs from the signed module"
            )
        for schema in (tool.input_schema, tool.output_schema):
            _check_schema(schema)
    for command in contribution.commands:
        for schema in (command.input_schema, command.output_schema):
            _check_schema(schema)


def _executable(
    archive: VerifiedBundleArchiveV2,
    plugin: PluginManifestV2,
    module: PluginModuleV2,
    artifacts: dict[str, bytes],
    binding: TenantBindingV2 | None,
) -> tuple[bytes, "OciWorkerSpec | None"]:
    worker = plugin.runtime == RuntimeKindV2.MCP
    media = "application/vnd.memstack.mcp-oci-worker.v1+json" if worker else "application/wasm"
    abi = "mcp.stdio" if worker else "invoke"
    guests = [
        a
        for a in archive.manifest.artifacts
        if a.target == DataPlaneTargetV2.PYTHON
        and a.media_type == media
        and a.digest == module.artifact.digest
    ]
    if len(guests) != 1 or module.entrypoint != abi:
        raise OptionalBusinessError(
            "invalid_package", "missing signed executable or invalid entrypoint"
        )
    guest = guests[0]
    if module.artifact.source != f"bundle://{plugin.plugin_id}/{guest.path}":
        raise OptionalBusinessError("invalid_package", "module source does not belong to package")
    content = artifacts[guest.path]
    if worker:
        if (
            binding is None
            or guest.path != "artifacts/worker.json"
            or not archive.manifest.provenance
        ):
            raise OptionalBusinessError(
                "invalid_package", "workers require a project and publisher provenance"
            )
        from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSpec

        if not isinstance(binding, ScopeBindingV2):
            # The descriptor is verified, but no project worker execution grant is minted.
            return b"", OciWorkerSpec.parse(content)
        return b"", OciWorkerSpec.from_archive(archive, raw=content, scope=binding)
    if len(content) > 8 * 1024 * 1024 or not content.startswith(b"\0asm"):
        raise OptionalBusinessError("invalid_package", "expected a bounded binary Wasm guest")
    return content, None


def _ui_files(
    contribution: "ContributionDocument", artifacts: dict[str, bytes]
) -> dict[str, bytes]:
    from memstack_plugin_sdk.contract import parse_bound_slot_ui, sha256_digest

    files = {}
    slots: set[tuple[str, str]] = set()
    commands = {command.command_id for command in contribution.commands}
    input_commands = frozenset(
        command.command_id for command in contribution.commands if command.accepts_input
    )
    for ui in contribution.ui:
        if "ui.slot" not in ui.permissions:
            raise OptionalBusinessError("invalid_package", "page is missing its slot permission")
        bindings = {(ui.slot, target) for target in ui.targets}
        if slots & bindings:
            raise OptionalBusinessError("invalid_package", "multiple pages claim the same slot")
        slots.update(bindings)
        data = artifacts.get(f"ui/{ui.path}")
        if data is None or sha256_digest(data) != ui.digest:
            raise OptionalBusinessError(
                "invalid_package", "UI content differs from its declaration"
            )
        parse_bound_slot_ui(json.loads(data), ui.slot, commands, input_commands)
        files[ui.path] = data
    # Several deep links can share a large workbench entry. PageAsset identity includes
    # both its path and its signed digest, so conflicting declarations still fail.
    for asset in dict.fromkeys(asset for page in contribution.pages for asset in page.assets):
        path = "pages/" + asset.path
        files[path] = asset.verify(artifacts.get(path, b""))
    return files


def _check_schema(schema: dict[str, object]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise OptionalBusinessError("invalid_package", error.message) from error
    pending = [DRAFT202012.create_resource(schema)]
    while pending:
        resource = pending.pop()
        node = resource.contents
        if isinstance(node, dict):
            for keyword in ("$ref", "$dynamicRef"):
                ref = node.get(keyword)
                if isinstance(ref, str) and not ref.startswith("#"):
                    raise OptionalBusinessError(
                        "invalid_package", "schema references must be local"
                    )
        pending.extend(resource.subresources())


def _bound_entry(
    bundle: BundleManifestV2, plugin: PluginManifestV2, binding: TenantBindingV2 | None
) -> ProfileEntryV2:
    if len(bundle.layers) != 1:
        raise OptionalBusinessError("invalid_package", "project package requires one bundle layer")
    layer = bundle.layers[0]
    if (
        len(layer.entries) != 1
        or layer.kind.value != "bundle"
        or layer.replacements
        or layer.disabled_entry_ids
    ):
        raise OptionalBusinessError("invalid_package", "unsupported project package layers")
    entry = layer.entries[0]
    if (
        entry.module_ref != plugin.modules[0].module_ref
        or entry.plugin_ref != plugin.plugin_id
        or not entry.enabled
        or entry.parent_entry_id
        or entry.isolate
        or entry.inject
        != {r.alias: r.service for r in plugin.modules[0].contract.services.requires}
    ):
        raise OptionalBusinessError("invalid_package", "expected one enabled signed module entry")
    permitted_scopes = {ScopeV2(kind=ScopeKindV2.ROOT)}
    if binding is not None:
        permitted_scopes.add(ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=binding.tenant_id))
        if isinstance(binding, ScopeBindingV2):
            permitted_scopes.add(
                ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id=binding.tenant_id,
                    project_id=binding.project_id,
                )
            )
    if layer.scope not in permitted_scopes or entry.scope not in permitted_scopes:
        raise OptionalBusinessError("forbidden", "package scope does not cover this project")
    return entry


def _quotas(package: QuotaV2, entry: QuotaV2, *, worker: bool) -> dict[str, int]:
    def limit(name: str, ceiling: int) -> int:
        values = (getattr(package, name), getattr(entry, name), ceiling)
        return min(v for v in values if v is not None)

    return {
        "fuel_budget": limit("max_wasm_fuel", 1_000_000),
        "memory_limit_bytes": limit("max_wasm_memory_bytes", 16 * 1024 * 1024),
        "wall_time_ms": limit("max_wall_time_ms", 30_000 if worker else 1000),
        "max_output_bytes": limit("max_output_bytes", 65536),
    }
