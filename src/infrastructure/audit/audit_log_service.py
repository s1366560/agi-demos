"""
Audit Logging Service

Tracks all sensitive operations for compliance and security.
Logs provider CRUD operations, configuration changes, and tenant assignments.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AuditLog

logger = logging.getLogger(__name__)


class AuditLogEntry(BaseModel):
    """Audit log entry model."""

    id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str | None = None  # User ID or system
    action: str  # e.g., "provider.created", "provider.updated"
    resource_type: str  # e.g., "provider", "tenant_mapping"
    resource_id: str | None = None
    tenant_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}  # noqa: RUF012


class AuditLogService:
    """
    Service for logging audit events.

    Supports multiple backends:
    - Database (for persistent storage)
    - File (for development/testing)
    - Console (for debugging)
    """

    def __init__(
        self,
        backend: str = "console",  # "database", "file", "console"
        log_file: str | None = None,
    ) -> None:
        """
        Initialize audit log service.

        Args:
            backend: Where to store logs ("database", "file", "console")
            log_file: File path if backend is "file"
        """
        self.backend = backend
        self.log_file = log_file

    async def log_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        actor: str | None = None,
        tenant_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLogEntry:
        """
        Log an audit event.

        Args:
            action: Action performed (e.g., "provider.created")
            resource_type: Type of resource (e.g., "provider")
            resource_id: ID of the resource
            actor: User or system performing the action
            tenant_id: Tenant ID if applicable
            details: Additional details about the event
            ip_address: IP address of the actor
            user_agent: User agent string

        Returns:
            AuditLogEntry that was created
        """
        entry = AuditLogEntry(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor or "system",
            tenant_id=tenant_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Store based on backend
        if self.backend == "database":
            await self._log_to_database(entry)
        elif self.backend == "file":
            await self._log_to_file(entry)
        else:  # console
            await self._log_to_console(entry)

        return entry

    async def _log_to_database(self, entry: AuditLogEntry) -> None:
        """Store audit log in database."""
        try:
            async with async_session_factory() as session:
                db_entry = AuditLog(
                    id=entry.id or self.generate_id(),
                    timestamp=entry.timestamp,
                    actor=entry.actor,
                    action=entry.action,
                    resource_type=entry.resource_type,
                    resource_id=entry.resource_id,
                    tenant_id=entry.tenant_id,
                    details=entry.details,
                    ip_address=entry.ip_address,
                    user_agent=entry.user_agent,
                )
                session.add(db_entry)
                await session.commit()
                logger.debug(f"Audit log saved: {entry.action} on {entry.resource_type}")
        except Exception as e:
            logger.error(f"Failed to log to database: {e}")
            # Fallback to console
            await self._log_to_console(entry)

    @staticmethod
    def generate_id() -> str:
        """Generate a unique ID for audit log entries."""
        from uuid import uuid4

        return str(uuid4())

    async def _log_to_file(self, entry: AuditLogEntry) -> None:
        """Store audit log in file."""
        try:
            import json
            from pathlib import Path

            if not self.log_file:
                logger.warning("No log file configured, falling back to console")
                await self._log_to_console(entry)
                return

            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "a") as f:
                f.write(json.dumps(entry.model_dump(), default=str) + "\n")

        except Exception as e:
            logger.error(f"Failed to log to file: {e}")
            await self._log_to_console(entry)

    async def _log_to_console(self, entry: AuditLogEntry) -> None:
        """Log audit entry to console."""
        log_msg = (
            f"AUDIT: {entry.action} | "
            f"Resource: {entry.resource_type}:{entry.resource_id} | "
            f"Actor: {entry.actor} | "
            f"Tenant: {entry.tenant_id or 'N/A'}"
        )
        if entry.details:
            log_msg += f" | Details: {entry.details}"

        logger.info(log_msg)

    # Convenience methods for common actions

    async def log_provider_created(
        self,
        provider_id: UUID,
        provider_name: str,
        provider_type: str,
        actor: str | None = None,
        tenant_id: str | None = None,
    ):
        """Log provider creation."""
        return await self.log_event(
            action="provider.created",
            resource_type="provider",
            resource_id=str(provider_id),
            actor=actor,
            tenant_id=tenant_id,
            details={
                "provider_name": provider_name,
                "provider_type": provider_type,
            },
        )

    async def log_provider_updated(
        self,
        provider_id: UUID,
        changes: dict[str, Any],
        actor: str | None = None,
        tenant_id: str | None = None,
    ):
        """Log provider update."""
        return await self.log_event(
            action="provider.updated",
            resource_type="provider",
            resource_id=str(provider_id),
            actor=actor,
            tenant_id=tenant_id,
            details={"changes": changes},
        )

    async def log_provider_deleted(
        self,
        provider_id: UUID,
        provider_name: str,
        actor: str | None = None,
        tenant_id: str | None = None,
    ):
        """Log provider deletion."""
        return await self.log_event(
            action="provider.deleted",
            resource_type="provider",
            resource_id=str(provider_id),
            actor=actor,
            tenant_id=tenant_id,
            details={"provider_name": provider_name},
        )

    async def log_provider_health_check(
        self,
        provider_id: UUID,
        status: str,
        response_time_ms: int | None = None,
        actor: str | None = None,
    ):
        """Log provider health check."""
        return await self.log_event(
            action="provider.health_check",
            resource_type="provider",
            resource_id=str(provider_id),
            actor=actor or "system",
            details={
                "status": status,
                "response_time_ms": response_time_ms,
            },
        )

    async def log_tenant_provider_assigned(
        self,
        tenant_id: str,
        provider_id: UUID,
        priority: int,
        actor: str | None = None,
    ):
        """Log tenant-provider assignment."""
        return await self.log_event(
            action="tenant_provider.assigned",
            resource_type="tenant_provider_mapping",
            resource_id=f"{tenant_id}:{provider_id}",
            actor=actor,
            tenant_id=tenant_id,
            details={
                "provider_id": str(provider_id),
                "priority": priority,
            },
        )

    async def log_tenant_provider_unassigned(
        self,
        tenant_id: str,
        provider_id: UUID,
        actor: str | None = None,
    ):
        """Log tenant-provider unassignment."""
        return await self.log_event(
            action="tenant_provider.unassigned",
            resource_type="tenant_provider_mapping",
            resource_id=f"{tenant_id}:{provider_id}",
            actor=actor,
            tenant_id=tenant_id,
            details={"provider_id": str(provider_id)},
        )


# Singleton instance
_audit_service: AuditLogService | None = None


def get_audit_service() -> AuditLogService:
    """Get or create singleton audit service instance."""
    global _audit_service
    if _audit_service is None:
        from src.configuration.config import get_settings

        settings = get_settings()
        _audit_service = AuditLogService(
            backend=settings.audit_log_backend,
            log_file=settings.audit_log_file,
        )
        logger.info(f"Audit service initialized with backend: {settings.audit_log_backend}")
    return _audit_service
