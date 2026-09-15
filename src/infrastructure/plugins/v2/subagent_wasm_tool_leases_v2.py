"""Re-lease exact inherited WASM capabilities for detached child operations.

Call only after parent snapshot and child allowlist filtering. No catalog-wide
selection occurs here: each replacement uses the original signed contribution
and its original grant authority (whose production implementation opens a fresh
SQL session on every authorization). Parent and child must share exact scope
and generation; parent disposal does not revoke the child's independent lease.
"""

from collections.abc import Sequence

from src.infrastructure.agent.processor import ToolDefinition

from .agent_operation_tool_contributions import _OperationToolAdapterV2
from .boundary import current_operation_context_v2
from .runtime import RuntimeV2Error
from .tool_set import TOOL_SET_CATALOG_SERVICE_V2, ToolSetContributionCatalogProtocolV2
from .wasm_tool_runtime import _WasmOperationToolV2


async def rebind_inherited_wasm_tool_leases_v2(
    definitions: Sequence[ToolDefinition],
) -> list[ToolDefinition]:
    """Preserve ordinary tools; reauthorize only actual leased WASM definitions."""
    result: list[ToolDefinition] = []
    for definition in definitions:
        adapter = definition._tool_instance
        if not isinstance(adapter, _OperationToolAdapterV2) or not isinstance(
            adapter.definition._tool_instance, _WasmOperationToolV2
        ):
            result.append(definition)
            continue
        captured = adapter.definition._tool_instance
        operation = current_operation_context_v2()
        if operation is captured.operation:
            result.append(definition)
            continue
        if (
            operation.descriptor != captured.operation.descriptor
            or operation.context.scope != captured.operation.context.scope
        ):
            raise RuntimeV2Error(
                "subagent_wasm_owner_mismatch", "Inherited WASM scope or generation differs"
            )
        catalog = operation.require(TOOL_SET_CATALOG_SERVICE_V2)
        if not isinstance(catalog, ToolSetContributionCatalogProtocolV2) or not any(
            source is captured.source for _, source in catalog.contributions()
        ):
            raise RuntimeV2Error(
                "subagent_wasm_source_mismatch", "Inherited WASM source is not registered"
            )
        rebound = await captured.source.prepare(operation, captured.authority)
        result.extend(rebound.definitions)
    return result
