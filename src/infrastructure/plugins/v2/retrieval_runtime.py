"""Generation-owned env retrieval runtime resource and lifecycle effect."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.domain.ports.services.retrieval_store_port import RetrievalStorePort

from .graph_runtime import GraphRuntimeServiceV2
from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

RETRIEVAL_RUNTIME_MODULE_V2 = "builtin://memstack/retrieval/env-runtime"
RETRIEVAL_RUNTIME_SERVICE_V2 = "service:retrieval.env-runtime"
RETRIEVAL_GRAPH_RUNTIME_INJECT_V2 = "graph_runtime"

type RetrievalRuntimeFactoryV2 = Callable[
    [GraphRuntimeServiceV2],
    Awaitable[RetrievalStorePort] | RetrievalStorePort,
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class RetrievalRuntimeServiceV2:
    """Exact env retrieval resource state owned by one staged generation."""

    retrieval_store: RetrievalStorePort | None
    unavailable_code: str | None = None

    @property
    def available(self) -> bool:
        return self.retrieval_store is not None

    def require(self) -> RetrievalStorePort:
        if self.retrieval_store is None:
            raise RuntimeV2Error(
                self.unavailable_code or "retrieval_runtime_unavailable",
                "env retrieval runtime is unavailable in the pinned generation",
            )
        return self.retrieval_store


def retrieval_runtime_definition_v2(
    retrieval_runtime_factory: RetrievalRuntimeFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Bind a data-plane factory while retaining a zero-argument entrypoint."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        strategy = config.get("strategy")
        required = config.get("required")
        if strategy != "memstack-pgvector":
            raise ValueError("env retrieval runtime requires strategy memstack-pgvector")
        if not isinstance(required, bool):
            raise ValueError("env retrieval runtime requires an explicit boolean required setting")

        graph_runtime = context.require(RETRIEVAL_GRAPH_RUNTIME_INJECT_V2)
        if not isinstance(graph_runtime, GraphRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_retrieval_graph_runtime",
                "env retrieval graph runtime inject has an invalid implementation",
            )

        if retrieval_runtime_factory is None:
            if required:
                raise RuntimeV2Error(
                    "retrieval_runtime_factory_unavailable",
                    "required env retrieval runtime has no data-plane factory",
                )
            _provide_retrieval_runtime_v2(
                context,
                RetrievalRuntimeServiceV2(
                    retrieval_store=None,
                    unavailable_code="retrieval_runtime_factory_unavailable",
                ),
            )
            return None

        retrieval_store = retrieval_runtime_factory(graph_runtime)
        if inspect.isawaitable(retrieval_store):
            retrieval_store = await retrieval_store
        _provide_retrieval_runtime_v2(
            context,
            RetrievalRuntimeServiceV2(retrieval_store=retrieval_store),
        )

        async def dispose() -> None:
            await _close_retrieval_store_v2(retrieval_store)

        return dispose

    return PluginDefinitionV2(
        module_ref=RETRIEVAL_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(RETRIEVAL_RUNTIME_MODULE_V2),
        apply=apply,
    )


def _provide_retrieval_runtime_v2(
    context: ContextV2,
    runtime: RetrievalRuntimeServiceV2,
) -> None:
    _ = context.provide(
        RETRIEVAL_RUNTIME_SERVICE_V2,
        runtime,
        label="env-retrieval-runtime",
    )


async def _close_retrieval_store_v2(retrieval_store: object) -> None:
    close = getattr(retrieval_store, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result
    logger.info("Env retrieval backend closed by generation disposer")


__all__ = [
    "RETRIEVAL_GRAPH_RUNTIME_INJECT_V2",
    "RETRIEVAL_RUNTIME_MODULE_V2",
    "RETRIEVAL_RUNTIME_SERVICE_V2",
    "RetrievalRuntimeFactoryV2",
    "RetrievalRuntimeServiceV2",
    "retrieval_runtime_definition_v2",
]
