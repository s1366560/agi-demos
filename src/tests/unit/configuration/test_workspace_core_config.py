"""Tests for the isolated Workspace Core runtime configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.configuration.workspace_core import (
    WorkspaceCoreMigrationMode,
    WorkspaceCoreSettings,
)


@pytest.mark.unit
class TestWorkspaceCoreSettings:
    @pytest.fixture(autouse=True)
    def isolate_workspace_core_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "WORKSPACE_CORE_BASE_URL",
            "WORKSPACE_CORE_SERVICE_TOKEN",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)

    def test_defaults_fail_closed_without_connection_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with pytest.raises(ValidationError, match="base URL and service token"):
            WorkspaceCoreSettings.model_validate({})

    def test_avernet_requires_endpoint_and_service_token(self) -> None:
        with pytest.raises(ValidationError, match="base URL and service token"):
            WorkspaceCoreSettings.model_validate({})

    def test_avernet_accepts_explicit_connection_contract(self) -> None:
        settings = WorkspaceCoreSettings.model_validate(
            {
                "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
                "WORKSPACE_CORE_SERVICE_TOKEN": "test-service-token",
                "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "test-webhook-token",
                "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "test-event-token",
                "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "test-registry-token",
                "WORKSPACE_CORE_REQUEST_TIMEOUT_SECONDS": 3.5,
            }
        )

        assert settings.migration_mode is WorkspaceCoreMigrationMode.DISABLED
        assert str(settings.base_url) == "http://127.0.0.1:4319/"
        assert settings.service_token is not None
        assert settings.service_token.get_secret_value() == "test-service-token"
        assert settings.provider_webhook_token is not None
        assert settings.provider_event_token is not None
        assert settings.agent_registry_token is not None
        assert settings.request_timeout_seconds == 3.5

    def test_avernet_requires_separate_provider_tokens(self) -> None:
        with pytest.raises(ValidationError, match="separate webhook and event tokens"):
            WorkspaceCoreSettings.model_validate(
                {
                    "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
                    "WORKSPACE_CORE_SERVICE_TOKEN": "test-service-token",
                }
            )

    def test_avernet_rejects_reused_credentials(self) -> None:
        with pytest.raises(ValidationError, match="separate tokens"):
            WorkspaceCoreSettings.model_validate(
                {
                    "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
                    "WORKSPACE_CORE_SERVICE_TOKEN": "same-token",
                    "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "same-token",
                    "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
                    "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
                }
            )

    def test_avernet_requires_dedicated_agent_registry_token(self) -> None:
        with pytest.raises(ValidationError, match="Agent Registry requires a dedicated token"):
            WorkspaceCoreSettings.model_validate(
                {
                    "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
                    "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
                    "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
                    "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
                }
            )

    def test_avernet_rejects_blank_service_token(self) -> None:
        with pytest.raises(ValidationError, match="base URL and service token"):
            WorkspaceCoreSettings.model_validate(
                {
                    "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
                    "WORKSPACE_CORE_SERVICE_TOKEN": "   ",
                }
            )
