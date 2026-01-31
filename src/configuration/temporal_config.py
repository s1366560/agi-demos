"""Temporal.io configuration for MemStack.

This module provides configuration settings for Temporal workflow orchestration,
including connection settings, worker configuration, and tenant isolation.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TemporalSettings(BaseSettings):
    """Temporal.io configuration settings."""

    # Connection Settings
    temporal_host: str = Field(default="localhost:7233", alias="TEMPORAL_HOST")
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")

    # TLS Configuration (for production)
    temporal_tls_enabled: bool = Field(default=False, alias="TEMPORAL_TLS_ENABLED")
    temporal_tls_cert_path: Optional[str] = Field(default=None, alias="TEMPORAL_TLS_CERT_PATH")
    temporal_tls_key_path: Optional[str] = Field(default=None, alias="TEMPORAL_TLS_KEY_PATH")
    temporal_tls_ca_path: Optional[str] = Field(default=None, alias="TEMPORAL_TLS_CA_PATH")

    # Task Queue Settings
    temporal_task_queue_prefix: str = Field(default="memstack", alias="TEMPORAL_TASK_QUEUE_PREFIX")
    temporal_default_task_queue: str = Field(
        default="memstack-default", alias="TEMPORAL_DEFAULT_TASK_QUEUE"
    )

    # Worker Configuration
    temporal_max_concurrent_activities: int = Field(
        default=100, alias="TEMPORAL_MAX_CONCURRENT_ACTIVITIES"
    )
    temporal_max_concurrent_workflows: int = Field(
        default=100, alias="TEMPORAL_MAX_CONCURRENT_WORKFLOWS"
    )
    temporal_max_concurrent_activity_task_pollers: int = Field(
        default=5, alias="TEMPORAL_MAX_CONCURRENT_ACTIVITY_TASK_POLLERS"
    )
    temporal_max_concurrent_workflow_task_pollers: int = Field(
        default=5, alias="TEMPORAL_MAX_CONCURRENT_WORKFLOW_TASK_POLLERS"
    )

    # Workflow Defaults
    temporal_default_workflow_timeout: int = Field(
        default=3600, alias="TEMPORAL_DEFAULT_WORKFLOW_TIMEOUT"
    )
    temporal_default_activity_timeout: int = Field(
        default=600, alias="TEMPORAL_DEFAULT_ACTIVITY_TIMEOUT"
    )
    temporal_default_heartbeat_timeout: int = Field(
        default=60, alias="TEMPORAL_DEFAULT_HEARTBEAT_TIMEOUT"
    )

    # Retry Configuration
    temporal_max_retry_attempts: int = Field(default=3, alias="TEMPORAL_MAX_RETRY_ATTEMPTS")
    temporal_initial_retry_interval: int = Field(default=1, alias="TEMPORAL_INITIAL_RETRY_INTERVAL")
    temporal_max_retry_interval: int = Field(default=600, alias="TEMPORAL_MAX_RETRY_INTERVAL")
    temporal_retry_backoff_coefficient: float = Field(
        default=2.0, alias="TEMPORAL_RETRY_BACKOFF_COEFFICIENT"
    )

    # Agent Worker Settings (Independent worker for agent workflows)
    agent_temporal_task_queue: str = Field(
        default="memstack-agent-tasks", alias="AGENT_TEMPORAL_TASK_QUEUE"
    )
    agent_worker_concurrency: int = Field(default=50, alias="AGENT_WORKER_CONCURRENCY")
    agent_provider_refresh_interval: int = Field(
        default=60, alias="AGENT_PROVIDER_REFRESH_INTERVAL"
    )

    # OpenTelemetry Tracing for Temporal client
    # Note: Named differently to avoid conflicts with global ENABLE_TELEMETRY env var
    temporal_tracing_enabled: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_task_queue_for_tenant(self, tenant_id: str) -> str:
        """Generate tenant-specific task queue name for isolation.

        Args:
            tenant_id: The tenant identifier

        Returns:
            Task queue name in format: {prefix}-tenant-{tenant_id}
        """
        return f"{self.temporal_task_queue_prefix}-tenant-{tenant_id}"

    def get_task_queue_for_project(self, project_id: str) -> str:
        """Generate project-specific task queue name.

        Args:
            project_id: The project identifier

        Returns:
            Task queue name in format: {prefix}-project-{project_id}
        """
        return f"{self.temporal_task_queue_prefix}-project-{project_id}"

    @property
    def temporal_address(self) -> str:
        """Get the Temporal server address."""
        return self.temporal_host


@lru_cache
def get_temporal_settings() -> TemporalSettings:
    """Get cached Temporal settings instance."""
    return TemporalSettings()
