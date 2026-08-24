"""Resolve Workspace Core resources from an immutable V2 generation boundary."""

from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI, Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import current_generation_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    WorkspaceCoreRuntimeServiceV2,
)
from src.infrastructure.workspace_core.client import WorkspaceCoreClient

_ROOT_SCOPE_V2 = ScopeV2(kind=ScopeKindV2.ROOT)


def workspace_core_runtime_service_v2_from_current_generation() -> WorkspaceCoreRuntimeServiceV2:
    """Resolve the runtime owned by the immutable generation pinned to this operation."""
    runtime = current_generation_v2().resolve(
        WORKSPACE_CORE_RUNTIME_SERVICE_V2,
        _ROOT_SCOPE_V2,
        version="1.0.0",
    )
    if not isinstance(runtime, WorkspaceCoreRuntimeServiceV2):
        raise TypeError("pinned generation has an invalid Workspace Core runtime service")
    return runtime


def workspace_core_runtime_service_v2_from_request(
    request: Request,
) -> WorkspaceCoreRuntimeServiceV2:
    """Resolve V2 authority, retaining V1 only when no generation boundary exists."""
    try:
        return workspace_core_runtime_service_v2_from_current_generation()
    except RuntimeV2Error as exc:
        if exc.code != "generation_not_pinned":
            raise
    return _legacy_workspace_core_runtime_service_v2_from_app(request.app)


def workspace_core_client_v2_from_request(request: Request) -> WorkspaceCoreClient:
    """Resolve the pinned client, with a no-boundary seam for isolated V1 tests."""
    try:
        return workspace_core_runtime_service_v2_from_current_generation().client
    except RuntimeV2Error as exc:
        if exc.code != "generation_not_pinned":
            raise
    legacy_client = getattr(request.app.state, "workspace_core_client", None)
    if legacy_client is not None:
        if not isinstance(legacy_client, WorkspaceCoreClient):
            raise TypeError("legacy Workspace Core client has an invalid type")
        return legacy_client
    return workspace_core_runtime_service_v2_from_app(request.app).client


def workspace_core_runtime_service_v2_from_app(app: FastAPI) -> WorkspaceCoreRuntimeServiceV2:
    """Resolve the exact static resource set exposed to isolated V1 tests."""
    runtime = getattr(app.state, "workspace_core_runtime_service_v2", None)
    if runtime is None:
        raise RuntimeError("Workspace Core runtime service V2 is not installed")
    if not isinstance(runtime, WorkspaceCoreRuntimeServiceV2):
        raise TypeError("Workspace Core runtime service V2 has an invalid type")
    return runtime


def _legacy_workspace_core_runtime_service_v2_from_app(
    app: FastAPI,
) -> WorkspaceCoreRuntimeServiceV2:
    """Project legacy test overrides without weakening a pinned generation."""
    runtime = workspace_core_runtime_service_v2_from_app(app)
    return replace(
        runtime,
        settings=getattr(app.state, "workspace_core_settings", runtime.settings),
        client=getattr(app.state, "workspace_core_client", runtime.client),
        authority=getattr(app.state, "workspace_authority", runtime.authority),
        context_judge=getattr(
            app.state,
            "workspace_core_context_judge",
            runtime.context_judge,
        ),
        plan_judge=getattr(app.state, "workspace_core_plan_judge", runtime.plan_judge),
        autonomy_judge=getattr(
            app.state,
            "workspace_core_autonomy_judge",
            runtime.autonomy_judge,
        ),
        event_sink=getattr(app.state, "workspace_core_event_sink", runtime.event_sink),
        provider_adapter=getattr(
            app.state,
            "workspace_core_provider_adapter",
            runtime.provider_adapter,
        ),
    )


__all__ = [
    "workspace_core_client_v2_from_request",
    "workspace_core_runtime_service_v2_from_app",
    "workspace_core_runtime_service_v2_from_current_generation",
    "workspace_core_runtime_service_v2_from_request",
]
