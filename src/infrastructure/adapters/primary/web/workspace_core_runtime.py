"""Install process-scoped Workspace Core clients and authority adapters."""

from __future__ import annotations

from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.plugins.v2.boundary import reserve_current_generation_v2
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WorkspaceCoreRuntimeServiceV2,
)
from src.infrastructure.workspace_core.agent_runtime_provider import (
    MemStackAgentRuntimeProvider,
)
from src.infrastructure.workspace_core.authority import AvernetWorkspaceAuthority
from src.infrastructure.workspace_core.autonomy_judge import AgentWorkspaceAutonomyJudge
from src.infrastructure.workspace_core.client import (
    AvernetWorkspaceAccessVerifier,
    WorkspaceCoreClient,
)
from src.infrastructure.workspace_core.compatibility import require_complete_public_api
from src.infrastructure.workspace_core.context_judge import AgentWorkspaceContextJudge
from src.infrastructure.workspace_core.plan_judge import AgentWorkspacePlanJudge
from src.infrastructure.workspace_core.provider import (
    AvernetBotEventHttpSink,
    AvernetProviderAdapter,
)


def _build_workspace_core_runtime_service_v2(
    settings: WorkspaceCoreSettings,
) -> WorkspaceCoreRuntimeServiceV2:
    """Construct one isolated candidate without publishing process authority."""
    client = WorkspaceCoreClient(settings)
    authority = AvernetWorkspaceAuthority(client)
    context_judge = AgentWorkspaceContextJudge()
    plan_judge = AgentWorkspacePlanJudge()
    autonomy_judge = AgentWorkspaceAutonomyJudge()

    assert settings.base_url is not None
    assert settings.provider_event_token is not None
    event_sink = AvernetBotEventHttpSink(
        base_url=str(settings.base_url),
        event_token=settings.provider_event_token.get_secret_value(),
        timeout_seconds=settings.request_timeout_seconds,
    )
    agent_runtime_provider = MemStackAgentRuntimeProvider(workspace_core_client=client)
    provider_adapter = AvernetProviderAdapter(
        agent_runtime_provider,
        event_sink,
        client,
        generation_reserver=reserve_current_generation_v2,
    )
    access_verifier = AvernetWorkspaceAccessVerifier(client)
    return WorkspaceCoreRuntimeServiceV2(
        settings=settings,
        client=client,
        authority=authority,
        context_judge=context_judge,
        plan_judge=plan_judge,
        autonomy_judge=autonomy_judge,
        access_verifier=access_verifier,
        event_sink=event_sink,
        agent_runtime_provider=agent_runtime_provider,
        provider_adapter=provider_adapter,
    )


async def create_workspace_core_runtime_service_v2(
    settings: WorkspaceCoreSettings,
) -> WorkspaceCoreRuntimeServiceV2:
    """Create and health-check a generation-owned Workspace Core candidate."""
    runtime = _build_workspace_core_runtime_service_v2(settings)
    try:
        capabilities = await runtime.client.read_public_api_capabilities()
        require_complete_public_api(capabilities)
    except Exception:
        await runtime.dispose()
        raise
    return runtime


def install_workspace_core_runtime(
    app: FastAPI,
    _settings: WorkspaceCoreSettings | None = None,
) -> None:
    """Mount only the frozen V1 Provider routes for inventory materialization."""
    from src.infrastructure.adapters.primary.web.workspace_core_provider import (
        router as workspace_core_provider_router,
    )

    app.include_router(workspace_core_provider_router)


def install_legacy_workspace_core_runtime(
    app: FastAPI,
    settings: WorkspaceCoreSettings,
) -> None:
    """Install process-state authority only for isolated V1 compatibility tests."""
    from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
        configure_workspace_access_verifier,
    )

    app.state.workspace_core_settings = settings
    install_workspace_core_runtime(app, settings)
    runtime = _build_workspace_core_runtime_service_v2(settings)
    app.state.workspace_core_runtime_service_v2 = runtime
    app.state.workspace_core_client = runtime.client
    app.state.workspace_authority = runtime.authority
    app.state.workspace_core_context_judge = runtime.context_judge
    app.state.workspace_core_plan_judge = runtime.plan_judge
    app.state.workspace_core_autonomy_judge = runtime.autonomy_judge
    app.state.workspace_core_event_sink = runtime.event_sink
    app.state.workspace_core_provider_adapter = runtime.provider_adapter
    configure_workspace_access_verifier(runtime.access_verifier)


async def start_workspace_core_runtime(app: FastAPI) -> None:
    """Verify the complete public contract before accepting traffic."""
    client = app.state.workspace_core_client
    if not isinstance(client, WorkspaceCoreClient):
        raise RuntimeError("Avernet Workspace Core client is not installed")
    capabilities = await client.read_public_api_capabilities()
    require_complete_public_api(capabilities)


async def shutdown_workspace_core_runtime(app: FastAPI) -> None:
    """Drain Provider callbacks before shared infrastructure stops."""
    provider_adapter = getattr(app.state, "workspace_core_provider_adapter", None)
    if provider_adapter is not None:
        await provider_adapter.wait_until_idle()
