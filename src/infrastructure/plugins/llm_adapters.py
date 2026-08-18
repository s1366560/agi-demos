"""Typed provider seam between LLM routing and adapter construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from src.domain.llm_providers.llm_types import LLMClient, LLMConfig
from src.domain.llm_providers.models import ProviderConfig
from src.domain.ports.plugins import ResolvedLlmRoute


@dataclass(frozen=True)
class LlmAdapterRequest:
    """Facts available to one provider adapter at its execution boundary."""

    route: ResolvedLlmRoute | None
    provider_config: ProviderConfig
    llm_config: LLMConfig | None
    adapter_kwargs: Mapping[str, Any]


@runtime_checkable
class LlmAdapterProvider(Protocol):
    """Service Definition for constructing provider-neutral LLM clients."""

    def create_adapter(self, request: LlmAdapterRequest) -> LLMClient: ...


class LegacyLlmAdapterProvider:
    """Compatibility provider backed by the existing LiteLLM adapter registry."""

    def __init__(self) -> None:
        from src.infrastructure.llm.registry import get_provider_adapter_registry

        self._registry = get_provider_adapter_registry()

    def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
        """Preserve the current adapter registry behavior behind one typed seam."""
        return self._registry.create_adapter(
            provider_config=request.provider_config,
            llm_config=request.llm_config,
            **dict(request.adapter_kwargs),
        )


def freeze_adapter_kwargs(kwargs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Snapshot adapter kwargs before provider dispatch."""
    return MappingProxyType(dict(kwargs))
