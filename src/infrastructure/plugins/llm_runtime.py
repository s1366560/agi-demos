"""Request-time LLM routing and credential lease enforcement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from src.domain.model.plugins import CredentialReference, PluginScopeContext
from src.domain.ports.plugins import ResolvedLlmRoute


class LlmRouteResolutionError(RuntimeError):
    """Raised when a provider route cannot be resolved safely."""


class CredentialLeaseError(RuntimeError):
    """Raised when a credential lease is unavailable or expired."""


@dataclass(frozen=True)
class ProviderRouteConfig:
    """Persistable provider route facts; secrets are references only."""

    provider_id: str
    provider_type: str
    model_id: str
    base_url: str
    credential_ref: str
    credential_revision: int
    timeout_ms: int = 120_000
    context_window: int = 128_000
    max_output_tokens: int = 8_192


class CredentialLeaseResolver(Protocol):
    """Host-owned resolver invoked at the execution boundary."""

    async def resolve(
        self,
        scope: PluginScopeContext,
        credential: CredentialReference,
    ) -> CredentialLease: ...


@dataclass(frozen=True)
class CredentialLease:
    """Short-lived credential value with redacted diagnostics."""

    value: str
    credential: CredentialReference
    expires_at_ms: int | None = None
    uses_remaining: int | None = None
    _released: bool = False

    def __repr__(self) -> str:
        return "CredentialLease(<redacted>)"

    @property
    def released(self) -> bool:
        """Return whether this lease has already been released."""
        return self._released

    def release(self) -> None:
        """Release the lease without exposing its value."""
        object.__setattr__(self, "_released", True)


class CredentialLeaseScope:
    """Release one credential lease deterministically."""

    def __init__(self, lease: CredentialLease) -> None:
        self._lease = lease

    async def __aenter__(self) -> CredentialLease:
        if self._lease.released:
            raise CredentialLeaseError("credential lease already released")
        if self._lease.uses_remaining == 0:
            raise CredentialLeaseError("credential lease exhausted")
        return self._lease

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._lease.release()


class LlmRouteResolver:
    """Resolve routes without freezing credentials into provider instances."""

    def __init__(
        self,
        providers: Mapping[str, ProviderRouteConfig],
        lease_resolver: CredentialLeaseResolver,
    ) -> None:
        self._providers = dict(providers)
        self._lease_resolver = lease_resolver

    def resolve(
        self,
        provider_id: str,
        model_id: str | None = None,
    ) -> ResolvedLlmRoute:
        """Resolve immutable route facts for one request."""
        config = self._providers.get(provider_id)
        if config is None:
            raise LlmRouteResolutionError(f"unknown LLM provider: {provider_id}")
        selected_model = model_id or config.model_id
        if not selected_model:
            raise LlmRouteResolutionError(f"provider {provider_id} has no selected model")
        return ResolvedLlmRoute(
            provider_id=config.provider_id,
            model_id=selected_model,
            base_url=config.base_url,
            credential=CredentialReference(
                ref=config.credential_ref,
                revision=config.credential_revision,
            ),
            timeout_ms=config.timeout_ms,
            context_window=config.context_window,
            max_output_tokens=config.max_output_tokens,
        )

    async def lease(
        self,
        scope: PluginScopeContext,
        route: ResolvedLlmRoute,
    ) -> CredentialLeaseScope:
        """Create a one-request credential scope for an execution boundary."""
        lease = await self._lease_resolver.resolve(scope, route.credential)
        return CredentialLeaseScope(lease)


class ProviderMetadataRegistry:
    """Provider-neutral metadata used by health and resilience consumers."""

    def __init__(self) -> None:
        self._metadata: dict[str, dict[str, Any]] = {}

    def register(self, provider_id: str, metadata: Mapping[str, Any]) -> None:
        """Replace metadata for one provider."""
        if not provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        self._metadata[provider_id] = dict(metadata)

    def get(self, provider_id: str) -> Mapping[str, Any]:
        """Return one provider metadata mapping."""
        try:
            return self._metadata[provider_id]
        except KeyError as exc:
            raise KeyError(provider_id) from exc

    def list(self) -> tuple[str, ...]:
        """Return deterministic provider ids."""
        return tuple(sorted(self._metadata))
