"""Generation-owned graph runtime resource and lifecycle effect."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.domain.llm_providers.models import NoActiveProviderError
from src.domain.ports.services.graph_store_port import GraphStorePort

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GRAPH_RUNTIME_MODULE_V2 = "builtin://memstack/graph/runtime"
GRAPH_RUNTIME_SERVICE_V2 = "service:graph.runtime"

type GraphRuntimeFactoryV2 = Callable[[], Awaitable[GraphStorePort]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GraphRuntimeServiceV2:
    """Exact graph resource state owned by one staged generation."""

    graph_service: GraphStorePort | None
    unavailable_code: str | None = None

    @property
    def available(self) -> bool:
        return self.graph_service is not None

    def require(self) -> GraphStorePort:
        if self.graph_service is None:
            raise RuntimeV2Error(
                self.unavailable_code or "graph_runtime_unavailable",
                "graph runtime is unavailable in the pinned generation",
            )
        return self.graph_service


def graph_runtime_definition_v2(
    graph_runtime_factory: GraphRuntimeFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Bind a production factory while retaining a loadable zero-argument entrypoint."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        strategy = config.get("strategy")
        required = config.get("required")
        if strategy != "native-adapter":
            raise ValueError("graph runtime requires strategy native-adapter")
        if not isinstance(required, bool):
            raise ValueError("graph runtime requires an explicit boolean required setting")

        if graph_runtime_factory is None:
            if required:
                raise RuntimeV2Error(
                    "graph_runtime_factory_unavailable",
                    "required graph runtime has no data-plane factory",
                )
            _provide_graph_runtime_v2(
                context,
                GraphRuntimeServiceV2(
                    graph_service=None,
                    unavailable_code="graph_runtime_factory_unavailable",
                ),
            )
            return None

        try:
            graph_service = await graph_runtime_factory()
        except NoActiveProviderError as exc:
            if required:
                raise RuntimeV2Error(
                    "no_active_provider",
                    "required graph runtime has no active model provider",
                ) from exc
            logger.warning("Graph runtime unavailable because no active provider is configured")
            _provide_graph_runtime_v2(
                context,
                GraphRuntimeServiceV2(
                    graph_service=None,
                    unavailable_code="no_active_provider",
                ),
            )
            return None

        _provide_graph_runtime_v2(
            context,
            GraphRuntimeServiceV2(graph_service=graph_service),
        )

        async def dispose() -> None:
            await _close_graph_service_v2(graph_service)

        return dispose

    return PluginDefinitionV2(
        module_ref=GRAPH_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(GRAPH_RUNTIME_MODULE_V2),
        apply=apply,
    )


def _provide_graph_runtime_v2(
    context: ContextV2,
    runtime: GraphRuntimeServiceV2,
) -> None:
    _ = context.provide(
        GRAPH_RUNTIME_SERVICE_V2,
        runtime,
        label="graph-runtime",
    )


async def _close_graph_service_v2(graph_service: object) -> None:
    close = getattr(graph_service, "close", None)
    if callable(close):
        result = close()
        if inspect.isawaitable(result):
            await result
        logger.info("Graph backend connection closed by generation disposer")
        return

    client = getattr(graph_service, "client", None)
    close_client = getattr(client, "close", None)
    if callable(close_client):
        result = close_client()
        if inspect.isawaitable(result):
            await result
        logger.info("Graph client connection closed by generation disposer")


__all__ = [
    "GRAPH_RUNTIME_MODULE_V2",
    "GRAPH_RUNTIME_SERVICE_V2",
    "GraphRuntimeFactoryV2",
    "GraphRuntimeServiceV2",
    "graph_runtime_definition_v2",
]
