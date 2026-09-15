"""Signed score-ABI tools; generation registration never implies operation permission.

C must call ``prepare_wasm_operation_tools_v2(operation, authority)`` inside the
real session operation before ToolSet resolution. The authority checks exact
installed artifact ownership and current tools.execute grants for that scope;
it is called again for every invocation, including after a lease was acquired.
No authority or no preparation means no visible tool. Preparation uses the
normal operation ToolDefinition leases, so operation disposal revokes retained
callbacks; generation disposal removes the source and closes its bounded host.
The result is Python/Cloud execution only, with UTF-8 JSON *byte* length ABI.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Protocol

from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DataPlaneTargetV2,
    PluginManifestV2,
    PluginModuleV2,
    RuntimeKindV2,
    ScopeKindV2,
    TrustKindV2,
)
from src.infrastructure.agent.processor import ToolDefinition
from src.infrastructure.plugins.wasm_host import (
    DEFAULT_FUEL_BUDGET,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_WALL_TIME_MS,
    WasmToolHost,
)

from .agent_operation_tool_contributions import lease_operation_tool_definitions_v2
from .runtime import ContextV2, FiberPhaseV2, OperationContextV2, PluginDefinitionV2, RuntimeV2Error
from .tool_set import TOOL_SET_CATALOG_SERVICE_V2, ToolSetContributionCatalogProtocolV2, ToolSetV2

OPERATION_WASM_TOOL_SETS_SERVICE_V2 = "service:operation.wasm-tool-sets"
_EMPTY_TOOLS = ToolSetV2(tools=MappingProxyType({}), definitions=())


@dataclass(frozen=True, kw_only=True)
class WasmToolAttributionV2:
    bundle_reference: BundleReferenceV2
    plugin_id: str
    plugin_version: str
    module_ref: str
    artifact_digest: str
    artifact_source: str
    entry_id: str
    tool_name: str
    effect: str = "pure"
    permission: str = "tools.execute"


class WasmOperationAuthorityV2(Protocol):
    async def authorize(
        self, *, operation: OperationContextV2, attribution: WasmToolAttributionV2
    ) -> bool:
        """Return True only for a current exact grant; recheck revocation on every call."""
        ...


@dataclass(frozen=True, kw_only=True)
class _PreparedWasmToolSetsV2:
    operation: OperationContextV2
    sources: Mapping[str, ToolSetV2]


def _input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"input": {"type": "string", "maxLength": 65536}},
        "required": ["input"],
        "additionalProperties": False,
    }


@dataclass(frozen=True, kw_only=True)
class _WasmOperationToolV2:
    source: _WasmContributionV2
    operation: OperationContextV2
    authority: WasmOperationAuthorityV2

    @property
    def tags(self) -> frozenset[str]:
        return frozenset({"wasm", "pure", "plugin"})

    @property
    def attribution(self) -> WasmToolAttributionV2:
        return self.source.attribution

    async def execute(self, **kwargs: object) -> str:
        from .boundary import current_operation_context_v2

        if current_operation_context_v2() is not self.operation:
            raise RuntimeV2Error(
                "wasm_operation_mismatch", "WASM tool belongs to another operation"
            )
        if not self.source.active or self.operation.phase is not FiberPhaseV2.ACTIVE:
            raise RuntimeV2Error("wasm_tool_revoked", "WASM contribution is no longer active")
        if (
            await self.authority.authorize(operation=self.operation, attribution=self.attribution)
            is not True
        ):
            raise RuntimeV2Error(
                "wasm_tool_permission_denied", "WASM execution permission is unavailable"
            )
        if not self.source.active or self.operation.phase is not FiberPhaseV2.ACTIVE:
            raise RuntimeV2Error("wasm_tool_revoked", "WASM contribution is no longer active")
        if (
            set(kwargs) != {"input"}
            or not isinstance(kwargs["input"], str)
            or len(kwargs["input"]) > 65536
        ):
            raise RuntimeV2Error(
                "wasm_input_invalid", "score ABI requires one bounded input string"
            )
        # No await occurs between the last authority check and dispatch except
        # bounded pure work. Revocation cannot acquire new capabilities here.
        payload = json.dumps(kwargs, ensure_ascii=False, separators=(",", ":"))
        outcome = await self.source.host.call_async(
            self.attribution.tool_name, payload, tenant_id=self.operation.context.scope.tenant_id
        )
        return json.dumps(
            {
                "score": outcome.score,
                "input_bytes": outcome.input_bytes,
                "fuel_consumed": outcome.fuel_consumed,
                "wall_time_ms": outcome.wall_time_ms,
                "attribution": asdict(self.attribution),
            },
            sort_keys=True,
        )


@dataclass
class _WasmContributionV2:
    host: WasmToolHost
    attribution: WasmToolAttributionV2
    active: bool = True

    @property
    def source_id(self) -> str:
        return f"wasm:{self.attribution.module_ref}:{self.attribution.entry_id}"

    def __call__(self, **_kwargs: object) -> ToolSetV2:
        from .boundary import current_operation_context_v2

        if not self.active:
            return _EMPTY_TOOLS
        try:
            operation = current_operation_context_v2()
            prepared = operation.require(OPERATION_WASM_TOOL_SETS_SERVICE_V2)
        except RuntimeV2Error as error:
            if error.code in {
                "operation_context_not_pinned",
                "missing_service",
                "inactive_operation",
            }:
                return _EMPTY_TOOLS
            raise
        if not isinstance(prepared, _PreparedWasmToolSetsV2) or prepared.operation is not operation:
            raise RuntimeV2Error("wasm_operation_mismatch", "invalid prepared WASM tool ownership")
        return prepared.sources.get(self.source_id, _EMPTY_TOOLS)

    async def prepare(
        self, operation: OperationContextV2, authority: WasmOperationAuthorityV2
    ) -> ToolSetV2:
        if (
            not self.active
            or await authority.authorize(operation=operation, attribution=self.attribution)
            is not True
        ):
            return _EMPTY_TOOLS
        tool = _WasmOperationToolV2(source=self, operation=operation, authority=authority)
        definition = ToolDefinition(
            name=self.attribution.tool_name,
            description=f"Pure signed WASM score tool from {self.attribution.plugin_id}@{self.attribution.plugin_version}. "
            "Receives the UTF-8 input JSON byte length as i32 and returns an i32 score.",
            parameters=_input_schema(),
            execute=tool.execute,
            permission="read",
            _tool_instance=tool,
        )
        return await lease_operation_tool_definitions_v2(
            operation=operation, source_id=self.source_id, definitions=[definition]
        )


async def prepare_wasm_operation_tools_v2(
    operation: OperationContextV2, authority: WasmOperationAuthorityV2
) -> int:
    """Prepare exact scoped grants; caller supplies the production grant authority.

    Only a live session scope with tenant/project/session identity is eligible.
    Permission denial hides that artifact. Unavailable authority raises and does
    not install a partial prepared service. Every retained callable is a normal
    operation lease and checks the same authority again before execution.
    """
    scope = operation.context.scope
    if scope.kind is not ScopeKindV2.SESSION or not all(
        (scope.tenant_id, scope.project_id, scope.session_id)
    ):
        raise RuntimeV2Error(
            "wasm_operation_scope_required", "WASM tools require a scoped session operation"
        )
    catalog = operation.require(TOOL_SET_CATALOG_SERVICE_V2)
    if not isinstance(catalog, ToolSetContributionCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_tool_catalog", "WASM preparation requires the tool contribution catalog"
        )
    sources = {}
    for source_id, contribution in catalog.contributions():
        if isinstance(contribution, _WasmContributionV2):
            sources[source_id] = await contribution.prepare(operation, authority)
    operation.provide(
        OPERATION_WASM_TOOL_SETS_SERVICE_V2,
        _PreparedWasmToolSetsV2(operation=operation, sources=MappingProxyType(sources)),
        label="prepared-wasm-tools",
    )
    return sum(len(source.definitions) for source in sources.values())


def create_verified_wasm_definition_v2(
    *,
    bundle_reference: BundleReferenceV2,
    manifest: PluginManifestV2,
    module: PluginModuleV2,
    artifact_bytes: bytes,
) -> PluginDefinitionV2:
    """Bind exact archive bytes; caller must have verified their signed archive.

    This is not a signature verifier. Loader admission supplies the authentic
    manifest/module pair. Compilation and ABI validation run off-loop during
    stage/apply, before registration. There are no imports or ambient callbacks.
    All quotas are capped by host ceilings, even if the manifest requests more.
    """
    _validate_contract(manifest, module, artifact_bytes)
    raw = bytes(artifact_bytes)

    async def apply(context: ContextV2, config: Mapping[str, object]) -> None:
        tool_name = config.get("tool_name")
        if (
            set(config) != {"tool_name"}
            or not isinstance(tool_name, str)
            or not tool_name
            or not all(c.isascii() and (c.isalnum() or c == "_") for c in tool_name)
        ):
            raise RuntimeV2Error(
                "wasm_tool_config_invalid", "WASM config requires one protocol tool_name"
            )
        name = f"wasm__{manifest.plugin_id}__{tool_name}"
        if len(name) > 64:
            raise RuntimeV2Error(
                "wasm_tool_name_invalid", "namespaced WASM tool name exceeds 64 bytes"
            )
        catalog = context.require("catalog")
        if not isinstance(catalog, ToolSetContributionCatalogProtocolV2):
            raise RuntimeV2Error(
                "invalid_tool_catalog", "WASM requires the normal tool contribution catalog"
            )

        async def acquire() -> Callable[[], Awaitable[None]]:
            compilation = asyncio.create_task(
                asyncio.to_thread(
                    WasmToolHost,
                    manifest.plugin_id,
                    raw,
                    fuel_budget=_bounded(manifest.quotas.max_wasm_fuel, DEFAULT_FUEL_BUDGET),
                    memory_limit_bytes=_bounded(
                        manifest.quotas.max_wasm_memory_bytes, DEFAULT_MEMORY_LIMIT_BYTES
                    ),
                    wall_time_ms=_bounded(manifest.quotas.max_wall_time_ms, DEFAULT_WALL_TIME_MS),
                )
            )
            try:
                host = await asyncio.shield(compilation)
            except asyncio.CancelledError:
                # Native compilation keeps running after coroutine cancellation.
                # Await its bounded artifact result so its resources are not orphaned.
                host = await compilation
                await asyncio.to_thread(host.close)
                raise
            contribution = _WasmContributionV2(
                host,
                WasmToolAttributionV2(
                    bundle_reference=bundle_reference,
                    plugin_id=manifest.plugin_id,
                    plugin_version=manifest.version,
                    module_ref=module.module_ref,
                    artifact_digest=module.artifact.digest,
                    artifact_source=module.artifact.source,
                    entry_id=context.entry_id,
                    tool_name=name,
                ),
            )
            try:
                unregister = catalog.register_tools(contribution.source_id, contribution)
            except BaseException:
                await asyncio.to_thread(host.close)
                raise

            async def dispose() -> None:
                contribution.active = False
                result = unregister()
                if result is not None:
                    await result
                await asyncio.to_thread(host.close)

            return dispose

        await context.effect(acquire, label=f"wasm-score:{module.module_ref}")

    return PluginDefinitionV2(
        module_ref=module.module_ref, contract_digest=module.contract_digest, apply=apply
    )


def _bounded(value: int | None, ceiling: int) -> int:
    if value is None:
        return ceiling
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeV2Error("wasm_quota_invalid", "WASM quotas must be positive integers")
    return min(value, ceiling)


def _validate_contract(manifest: PluginManifestV2, module: PluginModuleV2, raw: bytes) -> None:
    requirements = module.contract.services.requires
    valid = (
        manifest.runtime is RuntimeKindV2.WASM
        and manifest.trust is TrustKindV2.SIGNED
        and module in manifest.modules
        and module.targets == (DataPlaneTargetV2.PYTHON,)
        and module.entrypoint == "score"
        and not module.contract.services.provides
        and len(requirements) == 1
        and requirements[0].alias == "catalog"
        and requirements[0].service == TOOL_SET_CATALOG_SERVICE_V2
        and requirements[0].version == "1.0.0"
        and requirements[0].contributes is True
        and not module.contract.events.emits
        and not module.contract.events.handles
        and manifest.permissions == ("tools.execute",)
    )
    if not valid:
        raise RuntimeV2Error(
            "wasm_contract_forbidden",
            "external WASM supports only the fixed pure score contribution",
        )
    if len(raw) > 8 * 1024 * 1024 or not raw.startswith(b"\x00asm"):
        raise RuntimeV2Error("wasm_artifact_invalid", "WASM requires bounded binary artifact bytes")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != module.artifact.digest:
        raise RuntimeV2Error(
            "wasm_artifact_mismatch", "WASM bytes do not match the verified module digest"
        )
