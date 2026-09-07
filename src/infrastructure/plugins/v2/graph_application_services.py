"""Generation-owned graph application Consumer seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.domain.ports.services.graph_store_port import GraphStorePort

from .graph_runtime import GraphRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GRAPH_APPLICATION_MODULE_V2 = "builtin://memstack/application/graph-services"
GRAPH_APPLICATION_SERVICE_V2 = "service:application.graph-services"
GRAPH_APPLICATION_RUNTIME_INJECT_V2 = "graph_runtime"


@dataclass(frozen=True, kw_only=True)
class GraphApplicationServicesV2:
    """Exact graph resource state resolved from one pinned generation."""

    graph_runtime: GraphRuntimeServiceV2

    @property
    def available(self) -> bool:
        return self.graph_runtime.available

    @property
    def graph_store(self) -> GraphStorePort | None:
        return self.graph_runtime.graph_service

    @property
    def unavailable_code(self) -> str | None:
        return self.graph_runtime.unavailable_code


@runtime_checkable
class GraphApplicationResolverProtocolV2(Protocol):
    """Graph resolver injected through the public application service key."""

    def resolve(self, operation: OperationContextV2) -> GraphApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class GraphApplicationResolverV2:
    """Resolve graph resources without exposing the runtime Provider implementation."""

    graph_runtime: GraphRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> GraphApplicationServicesV2:
        _ = operation.descriptor
        return GraphApplicationServicesV2(graph_runtime=self.graph_runtime)


def _apply_graph_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "generation-runtime-services":
        raise ValueError("graph application resolver requires strategy generation-runtime-services")

    graph_runtime = context.require(GRAPH_APPLICATION_RUNTIME_INJECT_V2)
    if not isinstance(graph_runtime, GraphRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_graph_application_runtime",
            "graph application runtime inject has an invalid implementation",
        )

    _ = context.provide(
        GRAPH_APPLICATION_SERVICE_V2,
        GraphApplicationResolverV2(graph_runtime=graph_runtime),
        label="graph-application",
    )


def graph_application_service_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=GRAPH_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(GRAPH_APPLICATION_MODULE_V2),
        apply=_apply_graph_application_v2,
    )


__all__ = [
    "GRAPH_APPLICATION_MODULE_V2",
    "GRAPH_APPLICATION_RUNTIME_INJECT_V2",
    "GRAPH_APPLICATION_SERVICE_V2",
    "GraphApplicationResolverProtocolV2",
    "GraphApplicationResolverV2",
    "GraphApplicationServicesV2",
    "graph_application_service_definition_v2",
]
