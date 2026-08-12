"""Tests for Workspace Core client and access-verifier wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
    install_workspace_core_runtime,
    shutdown_workspace_core_runtime,
    start_workspace_core_runtime,
)
from src.infrastructure.workspace_core.autonomy_judge import AgentWorkspaceAutonomyJudge
from src.infrastructure.workspace_core.client import (
    AvernetWorkspaceAccessVerifier,
    WorkspaceCoreClient,
    WorkspaceCoreCompatibilityError,
)


def _settings(**overrides: object) -> WorkspaceCoreSettings:
    values: dict[str, object] = {
        "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
        "WORKSPACE_CORE_SERVICE_TOKEN": "internal-test-token",
        "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "provider-webhook-token",
        "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "provider-event-token",
        "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "agent-registry-token",
        **overrides,
    }
    return WorkspaceCoreSettings.model_validate(values)


@pytest.mark.unit
def test_legacy_without_shadow_has_no_core_client() -> None:
    app = FastAPI()

    with patch(
        "src.infrastructure.adapters.primary.web.workspace_core_runtime."
        "configure_workspace_access_verifier"
    ) as configure_verifier:
        install_workspace_core_runtime(app, WorkspaceCoreSettings.model_validate({}))

    assert app.state.workspace_core_client is None
    assert app.state.workspace_core_provider_adapter is None
    assert app.state.workspace_core_runtime_recovery_worker is None
    assert app.state.workspace_core_autonomy_judge is None
    configure_verifier.assert_called_once_with(None)


@pytest.mark.unit
def test_legacy_shadow_installs_client_but_keeps_legacy_access_authority() -> None:
    app = FastAPI()

    with patch(
        "src.infrastructure.adapters.primary.web.workspace_core_runtime."
        "configure_workspace_access_verifier"
    ) as configure_verifier:
        install_workspace_core_runtime(
            app,
            _settings(WORKSPACE_CORE_SHADOW_READ_ENABLED=True),
        )

    assert app.state.workspace_core_client is not None
    assert app.state.workspace_core_runtime_recovery_worker is None
    configure_verifier.assert_called_once_with(None)


@pytest.mark.unit
def test_avernet_installs_backend_access_verifier() -> None:
    app = FastAPI()

    with patch(
        "src.infrastructure.adapters.primary.web.workspace_core_runtime."
        "configure_workspace_access_verifier"
    ) as configure_verifier:
        install_workspace_core_runtime(
            app,
            _settings(WORKSPACE_CORE_BACKEND="avernet"),
        )

    verifier = configure_verifier.call_args.args[0]
    assert isinstance(verifier, AvernetWorkspaceAccessVerifier)
    assert isinstance(app.state.workspace_core_autonomy_judge, AgentWorkspaceAutonomyJudge)


@pytest.mark.unit
def test_avernet_injects_core_client_into_agent_runtime_provider() -> None:
    app = FastAPI()

    with (
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "configure_workspace_access_verifier"
        ),
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "MemStackAgentRuntimeProvider"
        ) as provider_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime.AvernetBotEventHttpSink"
        ) as event_sink_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime.AvernetProviderAdapter"
        ) as provider_adapter_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "AvernetRuntimeRecoveryWorker"
        ) as recovery_worker_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "AgentRuntimeRecoveryJudge"
        ) as judge_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "MemStackRuntimeRecoveryEvidence"
        ) as evidence_type,
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "default_runtime_recovery_config"
        ) as config_factory,
    ):
        install_workspace_core_runtime(
            app,
            _settings(WORKSPACE_CORE_BACKEND="avernet"),
        )

    provider_type.assert_called_once_with(workspace_core_client=app.state.workspace_core_client)
    provider_adapter_type.assert_called_once_with(
        provider_type.return_value,
        event_sink_type.return_value,
        app.state.workspace_core_client,
    )
    recovery_worker_type.assert_called_once_with(
        core_client=app.state.workspace_core_client,
        event_sink=event_sink_type.return_value,
        judge=judge_type.return_value,
        evidence=evidence_type.return_value,
        config=config_factory.return_value,
    )
    assert app.state.workspace_core_event_sink is event_sink_type.return_value
    assert app.state.workspace_core_provider_adapter is provider_adapter_type.return_value
    assert app.state.workspace_core_runtime_recovery_worker is recovery_worker_type.return_value


@pytest.mark.unit
async def test_start_workspace_core_runtime_starts_only_installed_worker() -> None:
    app = FastAPI()
    worker = MagicMock()
    app.state.workspace_core_settings = WorkspaceCoreSettings.model_validate({})
    app.state.workspace_core_runtime_recovery_worker = worker

    await start_workspace_core_runtime(app)

    worker.start.assert_called_once_with()


@pytest.mark.unit
async def test_avernet_start_verifies_capabilities_before_recovery() -> None:
    app = FastAPI()
    client = WorkspaceCoreClient(_settings(WORKSPACE_CORE_BACKEND="avernet"))
    read_capabilities = AsyncMock(return_value=MagicMock())
    worker = MagicMock()
    app.state.workspace_core_settings = _settings(WORKSPACE_CORE_BACKEND="avernet")
    app.state.workspace_core_client = client
    app.state.workspace_core_runtime_recovery_worker = worker

    with (
        patch.object(client, "read_public_api_capabilities", read_capabilities),
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "require_complete_public_api"
        ) as require_capabilities,
    ):
        await start_workspace_core_runtime(app)

    read_capabilities.assert_awaited_once_with()
    require_capabilities.assert_called_once_with(read_capabilities.return_value)
    worker.start.assert_called_once_with()


@pytest.mark.unit
async def test_avernet_start_does_not_start_recovery_when_capabilities_are_incomplete() -> None:
    app = FastAPI()
    client = WorkspaceCoreClient(_settings(WORKSPACE_CORE_BACKEND="avernet"))
    read_capabilities = AsyncMock(return_value=MagicMock())
    worker = MagicMock()
    app.state.workspace_core_settings = _settings(WORKSPACE_CORE_BACKEND="avernet")
    app.state.workspace_core_client = client
    app.state.workspace_core_runtime_recovery_worker = worker

    with (
        patch.object(client, "read_public_api_capabilities", read_capabilities),
        patch(
            "src.infrastructure.adapters.primary.web.workspace_core_runtime."
            "require_complete_public_api",
            side_effect=WorkspaceCoreCompatibilityError("incomplete"),
        ),
        pytest.raises(WorkspaceCoreCompatibilityError, match="incomplete"),
    ):
        await start_workspace_core_runtime(app)

    worker.start.assert_not_called()


@pytest.mark.unit
async def test_shutdown_workspace_core_runtime_stops_recovery_before_provider_drain() -> None:
    app = FastAPI()
    operations: list[str] = []
    worker = MagicMock()
    worker.stop = AsyncMock(side_effect=lambda: operations.append("stop"))
    provider_adapter = MagicMock()
    provider_adapter.wait_until_idle = AsyncMock(side_effect=lambda: operations.append("drain"))
    app.state.workspace_core_runtime_recovery_worker = worker
    app.state.workspace_core_provider_adapter = provider_adapter

    await shutdown_workspace_core_runtime(app)

    assert operations == ["stop", "drain"]
