"""Typed provider seam between LLM routing and adapter construction."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

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


class LlmAdapterFactory(Protocol):
    """Factory used by routed providers at the execution boundary."""

    def __call__(
        self,
        *,
        config: LLMConfig,
        provider_config: ProviderConfig,
        **kwargs: object,
    ) -> LLMClient: ...


class RoutedLlmAdapterProvider:
    """Provider that constructs clients from a typed route without the legacy registry."""

    def __init__(self, factory: LlmAdapterFactory | None = None) -> None:
        self._factory = factory or _default_litellm_factory

    def create_adapter(self, request: LlmAdapterRequest) -> LLMClient:
        """Create one client from the resolved route and immutable provider facts."""
        route = request.route
        if route is None:
            raise RuntimeError("routed LLM adapters require a resolved platform route")
        expected_provider = request.provider_config.provider_type.value
        if route.provider_id != expected_provider:
            raise RuntimeError(
                f"LLM route provider {route.provider_id} does not match {expected_provider}"
            )
        base_config = request.llm_config or LLMConfig(
            model=route.model_id,
            base_url=route.base_url,
            max_tokens=route.max_output_tokens,
        )
        config = replace(
            base_config,
            model=route.model_id,
            base_url=route.base_url,
        )
        return self._factory(
            config=config,
            provider_config=request.provider_config,
            **dict(request.adapter_kwargs),
        )


def _default_litellm_factory(
    *,
    config: LLMConfig,
    provider_config: ProviderConfig,
    **kwargs: object,
) -> LLMClient:
    """Construct the existing LiteLLM client without the provider adapter registry."""
    from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

    return cast(LlmAdapterFactory, LiteLLMClient)(
        config=config,
        provider_config=provider_config,
        **kwargs,
    )


@dataclass(frozen=True)
class LlmAdapterRegistration:
    """One reversible adapter provider registration."""

    provider_id: str
    owner: str
    provider: LlmAdapterProvider


class LlmAdapterProviderRegistry:
    """Thread-safe, reversible registry for explicit adapter providers."""

    def __init__(self) -> None:
        self._providers: dict[str, LlmAdapterRegistration] = {}
        self._lock = threading.RLock()

    def register(
        self,
        provider_id: str,
        provider: LlmAdapterProvider,
        *,
        owner: str = "kernel",
    ) -> Callable[[], None]:
        """Register one provider and return its disposer."""
        normalized_provider_id = provider_id.strip()
        normalized_owner = owner.strip()
        if not normalized_provider_id or not normalized_owner:
            raise ValueError("provider_id and owner must be non-empty")
        with self._lock:
            existing = self._providers.get(normalized_provider_id)
            if existing is not None:
                raise ValueError(
                    f"LLM adapter provider {normalized_provider_id} is already owned by "
                    f"{existing.owner}"
                )
            self._providers[normalized_provider_id] = LlmAdapterRegistration(
                provider_id=normalized_provider_id,
                owner=normalized_owner,
                provider=provider,
            )

        def dispose() -> None:
            self.unregister(normalized_provider_id, owner=normalized_owner)

        return dispose

    def unregister(self, provider_id: str, *, owner: str) -> None:
        """Remove a provider only when ownership still matches."""
        with self._lock:
            existing = self._providers.get(provider_id)
            if existing is not None and existing.owner == owner:
                del self._providers[provider_id]

    def replace(
        self,
        provider_id: str,
        provider: LlmAdapterProvider,
        *,
        owner: str,
    ) -> Callable[[], None]:
        """Atomically replace a provider owned by the same actor."""
        normalized_owner = owner.strip()
        with self._lock:
            existing = self._providers.get(provider_id.strip())
            if existing is not None and existing.owner != normalized_owner:
                raise ValueError(
                    f"LLM adapter provider {provider_id} is already owned by {existing.owner}"
                )
        self.unregister(provider_id.strip(), owner=normalized_owner)
        return self.register(provider_id, provider, owner=normalized_owner)

    def get(self, provider_id: str) -> LlmAdapterProvider | None:
        """Return the currently active explicit provider."""
        with self._lock:
            record = self._providers.get(provider_id)
            return None if record is None else record.provider

    def owner_of(self, provider_id: str) -> str | None:
        """Return the current provider owner for conflict-safe lifecycle checks."""
        with self._lock:
            record = self._providers.get(provider_id)
            return None if record is None else record.owner

    def list(self) -> tuple[LlmAdapterRegistration, ...]:
        """Return deterministic registration inventory."""
        with self._lock:
            return tuple(self._providers[key] for key in sorted(self._providers))


_adapter_provider_registry = LlmAdapterProviderRegistry()


def get_llm_adapter_provider_registry() -> LlmAdapterProviderRegistry:
    """Return the process-local adapter provider registry."""
    return _adapter_provider_registry


def freeze_adapter_kwargs(kwargs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Snapshot adapter kwargs before provider dispatch."""
    return MappingProxyType(dict(kwargs))
