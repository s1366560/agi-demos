"""Runtime-only provider/model identity for agent execution."""

from __future__ import annotations

from dataclasses import dataclass

from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error


@dataclass(frozen=True, slots=True)
class ModelRouteRef:
    """Minimal immutable route identity carried across the agent runtime.

    The provider is always supplied explicitly. This value object deliberately
    performs no catalog lookup, alias normalization, prefix parsing, or model
    name inference.
    """

    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip()
        model_id = self.model_id.strip()
        if not provider_id:
            raise RuntimeV2Error(
                "model_route_provider_missing",
                "model route provider_id must be non-empty",
            )
        if not model_id:
            raise RuntimeV2Error(
                "model_route_model_missing",
                "model route model_id must be non-empty",
            )
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", model_id)


__all__ = ["ModelRouteRef"]
