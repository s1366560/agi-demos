"""Runtime lookup for plugin-provided workspace pipeline providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.infrastructure.agent.workspace_plan.pipeline import PipelineContractSpec, PipelineRunResult
from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

PIPELINE_PROVIDER_SERVICE_PREFIX_V2 = "service:workspace.pipeline-provider."


@runtime_checkable
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
    """Resolve a pipeline provider only from the pinned V2 operation generation."""

    normalized_provider = _normalize_provider(provider)
    service_key = f"{PIPELINE_PROVIDER_SERVICE_PREFIX_V2}{normalized_provider}"
    try:
        candidate = current_operation_context_v2().require(service_key)
    except RuntimeV2Error as exc:
        if exc.code == "missing_service":
            return None
        raise
    if not isinstance(candidate, PipelineProvider):
        raise RuntimeV2Error(
            "invalid_pipeline_provider",
            f"pipeline provider service {service_key} has an invalid implementation",
        )
    return candidate


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
    "PIPELINE_PROVIDER_SERVICE_PREFIX_V2",
    "PipelineProvider",
    "PipelineProviderUnavailableError",
    "require_pipeline_provider",
    "resolve_pipeline_provider",
]
