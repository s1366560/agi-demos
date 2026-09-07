"""Thin projection from a pinned boundary to Artifact lifecycle services."""

from __future__ import annotations

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .artifact_lifecycle_services import (
    ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
    ArtifactLifecycleApplicationServiceV2,
)
from .boundary import current_generation_v2
from .runtime import RuntimeV2Error


def current_artifact_lifecycle_application_service_v2() -> ArtifactLifecycleApplicationServiceV2:
    """Resolve Artifact lifecycle behavior from the exact pinned generation."""
    service = current_generation_v2().resolve(
        ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(service, ArtifactLifecycleApplicationServiceV2):
        raise RuntimeV2Error(
            "invalid_artifact_lifecycle_application_service",
            "Artifact lifecycle application service has an invalid implementation",
        )
    return service


__all__ = ["current_artifact_lifecycle_application_service_v2"]
