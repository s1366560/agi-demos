"""Runtime lookup for plugin-provided workspace pipeline providers."""

from __future__ import annotations

import inspect
from typing import Protocol, cast

from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.plugins.registry import get_plugin_registry
from src.infrastructure.agent.workspace_plan.pipeline import PipelineContractSpec, PipelineRunResult

PIPELINE_PROVIDER_PREFIX = "pipeline:"


class PipelineProvider(Protocol):
    """Minimal pipeline provider contract used by workspace orchestration."""

    async def run(self, contract: PipelineContractSpec) -> PipelineRunResult:
        """Run the pipeline contract and return provider-normalized evidence."""
        ...


class PipelineProviderUnavailableError(LookupError):
    """Raised when the requested provider plugin is not enabled."""

    def __init__(self, provider: str) -> None:
        self.provider = _normalize_provider(provider)
        super().__init__(f"pipeline provider plugin is not enabled: {self.provider}")


async def resolve_pipeline_provider(provider: str) -> PipelineProvider | None:
    """Resolve a pipeline provider from the plugin registry."""

    normalized_provider = _normalize_provider(provider)
    _ = await get_plugin_runtime_manager().ensure_loaded()
    registered = get_plugin_registry().get_provider(
        f"{PIPELINE_PROVIDER_PREFIX}{normalized_provider}"
    )
    if registered is None:
        return None
    if isinstance(registered, type):
        candidate = registered()
        return cast(PipelineProvider, candidate) if hasattr(candidate, "run") else None
    if hasattr(registered, "run"):
        return cast(PipelineProvider, registered)
    if callable(registered):
        candidate = registered()
        if inspect.isawaitable(candidate):
            candidate = await candidate
        if candidate is not None:
            return cast(PipelineProvider, candidate) if hasattr(candidate, "run") else None
    return None


async def require_pipeline_provider(provider: str) -> PipelineProvider:
    """Resolve a pipeline provider or raise a stable plugin-disabled error."""

    normalized_provider = _normalize_provider(provider)
    resolved = await resolve_pipeline_provider(normalized_provider)
    if resolved is None:
        raise PipelineProviderUnavailableError(normalized_provider)
    return resolved


def _normalize_provider(provider: str | None) -> str:
    return (provider or "").strip().lower().replace("-", "_")


__all__ = [
    "PIPELINE_PROVIDER_PREFIX",
    "PipelineProvider",
    "PipelineProviderUnavailableError",
    "require_pipeline_provider",
    "resolve_pipeline_provider",
]
