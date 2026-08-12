"""Isolated configuration for the Workspace Core authority switch."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkspaceCoreBackend(StrEnum):
    """Workspace authority selected for the whole process."""

    LEGACY = "legacy"
    AVERNET = "avernet"


class WorkspaceCoreMigrationMode(StrEnum):
    """Migration behavior allowed for this process."""

    DISABLED = "disabled"
    DRY_RUN = "dry-run"
    EXECUTE = "execute"


class WorkspaceCoreSettings(BaseSettings):
    """Strict, process-scoped Workspace Core settings.

    This intentionally remains separate from the global application ``Settings``
    because switching Workspace authority is an atomic deployment decision.
    """

    backend: WorkspaceCoreBackend = Field(
        default=WorkspaceCoreBackend.LEGACY,
        alias="WORKSPACE_CORE_BACKEND",
    )
    migration_mode: WorkspaceCoreMigrationMode = Field(
        default=WorkspaceCoreMigrationMode.DISABLED,
        alias="WORKSPACE_CORE_MIGRATION_MODE",
    )
    base_url: HttpUrl | None = Field(default=None, alias="WORKSPACE_CORE_BASE_URL")
    service_token: SecretStr | None = Field(
        default=None,
        alias="WORKSPACE_CORE_SERVICE_TOKEN",
        repr=False,
    )
    provider_webhook_token: SecretStr | None = Field(
        default=None,
        alias="WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
        repr=False,
    )
    provider_event_token: SecretStr | None = Field(
        default=None,
        alias="WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
        repr=False,
    )
    agent_registry_token: SecretStr | None = Field(
        default=None,
        alias="WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
        repr=False,
    )
    shadow_read_enabled: bool = Field(
        default=False,
        alias="WORKSPACE_CORE_SHADOW_READ_ENABLED",
    )
    request_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=60,
        alias="WORKSPACE_CORE_REQUEST_TIMEOUT_SECONDS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    @field_validator(
        "service_token",
        "provider_webhook_token",
        "provider_event_token",
        "agent_registry_token",
        mode="before",
    )
    @classmethod
    def normalize_blank_service_token(cls, value: object) -> object | None:
        """Treat blank token configuration as missing credentials."""
        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw_value, str) and not raw_value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_avernet_connection_contract(self) -> Self:
        """Reject an incomplete Avernet authority selection."""
        connection_required = (
            self.backend is WorkspaceCoreBackend.AVERNET or self.shadow_read_enabled
        )
        if connection_required and (self.base_url is None or self.service_token is None):
            raise ValueError("Workspace Core connection requires a base URL and service token")
        if self.backend is WorkspaceCoreBackend.AVERNET and (
            self.provider_webhook_token is None or self.provider_event_token is None
        ):
            raise ValueError("Avernet Provider requires separate webhook and event tokens")
        if self.backend is WorkspaceCoreBackend.AVERNET and self.agent_registry_token is None:
            raise ValueError("Avernet Agent Registry requires a dedicated token")
        configured_tokens = [
            token.get_secret_value()
            for token in (
                self.service_token,
                self.provider_webhook_token,
                self.provider_event_token,
                self.agent_registry_token,
            )
            if token is not None
        ]
        if len(configured_tokens) != len(set(configured_tokens)):
            raise ValueError("Workspace Core credentials must use separate tokens")
        return self

    @property
    def connection_enabled(self) -> bool:
        """Return whether this process may call the Avernet core."""
        return self.backend is WorkspaceCoreBackend.AVERNET or self.shadow_read_enabled


@lru_cache
def get_workspace_core_settings() -> WorkspaceCoreSettings:
    """Return the immutable Workspace Core process configuration."""
    return WorkspaceCoreSettings()
