"""Install process-scoped Workspace Core clients and authority adapters."""

from __future__ import annotations

from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreBackend, WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
    configure_workspace_access_verifier,
)
from src.infrastructure.adapters.primary.web.workspace_core_provider import (
    router as workspace_core_provider_router,
)
from src.infrastructure.workspace_core.agent_runtime_provider import (
    MemStackAgentRuntimeProvider,
)
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
from src.infrastructure.workspace_core.runtime_recovery import (
    AgentRuntimeRecoveryJudge,
    AvernetRuntimeRecoveryWorker,
    MemStackRuntimeRecoveryEvidence,
    default_runtime_recovery_config,
)


def install_workspace_core_runtime(app: FastAPI, settings: WorkspaceCoreSettings) -> None:
    """Freeze one Workspace authority and optional shadow client on the app."""
    app.state.workspace_core_settings = settings
    app.include_router(workspace_core_provider_router)
    client = WorkspaceCoreClient(settings) if settings.connection_enabled else None
    app.state.workspace_core_client = client
    app.state.workspace_core_context_judge = (
        AgentWorkspaceContextJudge() if settings.backend is WorkspaceCoreBackend.AVERNET else None
    )
    app.state.workspace_core_plan_judge = (
        AgentWorkspacePlanJudge() if settings.backend is WorkspaceCoreBackend.AVERNET else None
    )
    app.state.workspace_core_autonomy_judge = (
        AgentWorkspaceAutonomyJudge() if settings.backend is WorkspaceCoreBackend.AVERNET else None
    )

    provider_adapter = None
    recovery_worker = None
    event_sink = None
    if settings.backend is WorkspaceCoreBackend.AVERNET:
        assert settings.base_url is not None
        assert settings.provider_event_token is not None
        assert client is not None
        event_sink = AvernetBotEventHttpSink(
            base_url=str(settings.base_url),
            event_token=settings.provider_event_token.get_secret_value(),
            timeout_seconds=settings.request_timeout_seconds,
        )
        provider_adapter = AvernetProviderAdapter(
            MemStackAgentRuntimeProvider(workspace_core_client=client),
            event_sink,
            client,
        )
        recovery_worker = AvernetRuntimeRecoveryWorker(
            core_client=client,
            event_sink=event_sink,
            judge=AgentRuntimeRecoveryJudge(),
            evidence=MemStackRuntimeRecoveryEvidence(),
            config=default_runtime_recovery_config(),
        )
    app.state.workspace_core_event_sink = event_sink
    app.state.workspace_core_provider_adapter = provider_adapter
    app.state.workspace_core_runtime_recovery_worker = recovery_worker

    verifier = (
        AvernetWorkspaceAccessVerifier(client)
        if settings.backend is WorkspaceCoreBackend.AVERNET and client is not None
        else None
    )
    configure_workspace_access_verifier(verifier)


async def start_workspace_core_runtime(app: FastAPI) -> None:
    """Verify the complete public contract, then start background recovery."""
    settings = app.state.workspace_core_settings
    if settings.backend is WorkspaceCoreBackend.AVERNET:
        client = app.state.workspace_core_client
        if not isinstance(client, WorkspaceCoreClient):
            raise RuntimeError("Avernet Workspace Core client is not installed")
        capabilities = await client.read_public_api_capabilities()
        require_complete_public_api(capabilities)

    worker = getattr(app.state, "workspace_core_runtime_recovery_worker", None)
    if worker is not None:
        worker.start()


async def shutdown_workspace_core_runtime(app: FastAPI) -> None:
    """Drain recovery and Provider callbacks before shared infrastructure stops."""
    worker = getattr(app.state, "workspace_core_runtime_recovery_worker", None)
    if worker is not None:
        await worker.stop()
    provider_adapter = getattr(app.state, "workspace_core_provider_adapter", None)
    if provider_adapter is not None:
        await provider_adapter.wait_until_idle()
