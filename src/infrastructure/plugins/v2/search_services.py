"""Generation-owned enhanced-search application Consumer seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort

from .graph_runtime import GraphRuntimeServiceV2
from .retrieval_runtime import RetrievalRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SEARCH_APPLICATION_MODULE_V2 = "builtin://memstack/application/search-services"
SEARCH_APPLICATION_SERVICE_V2 = "service:application.search-services"
SEARCH_GRAPH_RUNTIME_INJECT_V2 = "graph_runtime"
SEARCH_RETRIEVAL_RUNTIME_INJECT_V2 = "retrieval_runtime"


@dataclass(frozen=True, kw_only=True)
class SearchApplicationServicesV2:
    """Generation-owned graph and retrieval resources for one search operation."""

    graph_service: GraphStorePort
    retrieval_runtime: RetrievalRuntimeServiceV2

    @property
    def retrieval_store(self) -> RetrievalStorePort | None:
        """Return the explicitly optional retrieval resource for this generation."""
        return self.retrieval_runtime.retrieval_store


@runtime_checkable
class SearchApplicationResolverProtocolV2(Protocol):
    """Search resolver injected through the public application service key."""

    def resolve(self, operation: OperationContextV2) -> SearchApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SearchApplicationResolverV2:
    """Resolve search resources without exposing runtime Provider implementations."""

    graph_runtime: GraphRuntimeServiceV2
    retrieval_runtime: RetrievalRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> SearchApplicationServicesV2:
        _ = operation.descriptor
        return SearchApplicationServicesV2(
            graph_service=self.graph_runtime.require(),
            retrieval_runtime=self.retrieval_runtime,
        )


def _apply_search_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "generation-runtime-services":
        raise ValueError(
            "search application resolver requires strategy generation-runtime-services"
        )

    graph_runtime = context.require(SEARCH_GRAPH_RUNTIME_INJECT_V2)
    if not isinstance(graph_runtime, GraphRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_search_graph_runtime",
            "search graph runtime inject has an invalid implementation",
        )
    retrieval_runtime = context.require(SEARCH_RETRIEVAL_RUNTIME_INJECT_V2)
    if not isinstance(retrieval_runtime, RetrievalRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_search_retrieval_runtime",
            "search retrieval runtime inject has an invalid implementation",
        )

    _ = context.provide(
        SEARCH_APPLICATION_SERVICE_V2,
        SearchApplicationResolverV2(
            graph_runtime=graph_runtime,
            retrieval_runtime=retrieval_runtime,
        ),
        label="search-application",
    )


def search_service_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SEARCH_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SEARCH_APPLICATION_MODULE_V2),
        apply=_apply_search_application_v2,
    )


__all__ = [
    "SEARCH_APPLICATION_MODULE_V2",
    "SEARCH_APPLICATION_SERVICE_V2",
    "SEARCH_GRAPH_RUNTIME_INJECT_V2",
    "SEARCH_RETRIEVAL_RUNTIME_INJECT_V2",
    "SearchApplicationResolverProtocolV2",
    "SearchApplicationResolverV2",
    "SearchApplicationServicesV2",
    "search_service_definition_v2",
]
