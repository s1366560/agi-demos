"""Sandbox Reconciler - Startup state reconciliation for sandbox lifecycle.

This module handles the reconciliation of sandbox state on API startup:
- Discovers orphan Docker containers
- Syncs in-memory state with actual container states
- Handles orphan adoption or termination
- Ensures database and Docker state consistency

This fixes the issue where API restarts leave containers without tracking.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OrphanAction(Enum):
    """Action to take for orphan containers."""

    ADOPT = "adopt"  # Adopt into tracking system
    TERMINATE = "terminate"  # Terminate the container
    IGNORE = "ignore"  # Leave as-is (manual intervention needed)


@dataclass
class OrphanContainer:
    """Represents an orphan container discovered during reconciliation."""

    container_id: str
    container_name: str
    sandbox_id: str
    project_id: str | None
    tenant_id: str | None
    status: str  # Docker status: running, stopped, etc.
    ports: dict[str, int]  # service_type -> port
    labels: dict[str, str]
    created_at: datetime
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    action_taken: OrphanAction | None = None
    error_message: str | None = None


@dataclass
class ReconciliationResult:
    """Result of a reconciliation operation."""

    discovered_orphans: int
    adopted: int
    terminated: int
    errors: int
    orphan_containers: list[OrphanContainer]
    duration_seconds: float


class SandboxReconciler:
    """
    Reconciles sandbox state between Docker and the application.

    This class handles startup reconciliation to ensure the application's
    view of sandboxes matches the actual Docker container state. It:

    1. Discovers containers with memstack.sandbox labels
    2. Identifies which are orphans (not in memory tracking)
    3. Checks which have valid database associations
    4. Applies the configured action (adopt/terminate/ignore)

    Usage:
        reconciler = SandboxReconciler(
            docker_client=docker_client,
            sandbox_adapter=adapter,
            repository=repo,
            default_action=OrphanAction.ADOPT,
        )

        # Run on startup
        result = await reconciler.reconcile()

        # Or get orphan list for manual handling
        orphans = await reconciler.discover_orphans()
    """

    def __init__(
        self,
        docker_client,
        sandbox_adapter,
        repository=None,
        default_action: OrphanAction = OrphanAction.ADOPT,
        max_orphan_age_hours: int = 24,  # Terminate orphans older than this
    ) -> None:
        """
        Initialize the reconciler.

        Args:
            docker_client: Docker client instance
            sandbox_adapter: The MCP sandbox adapter for tracking
            repository: Optional ProjectSandbox repository for DB checks
            default_action: Default action for orphan containers
            max_orphan_age_hours: Maximum age before orphans are terminated regardless
        """
        self._docker = docker_client
        self._adapter = sandbox_adapter
        self._repository = repository
        self._default_action = default_action
        self._max_orphan_age_hours = max_orphan_age_hours

    async def reconcile(
        self,
        action_override: OrphanAction | None = None,
    ) -> ReconciliationResult:
        """
        Perform full reconciliation of sandbox state.

        This method:
        1. Discovers all orphan containers
        2. Applies the appropriate action to each
        3. Updates tracking state

        Args:
            action_override: Override the default action for this reconciliation

        Returns:
            ReconciliationResult with statistics
        """
        import time

        start_time = time.time()

        # Discover orphans
        orphans = await self.discover_orphans()

        action = action_override or self._default_action

        adopted = 0
        terminated = 0
        errors = 0

        for orphan in orphans:
            try:
                # Check age - very old orphans should always be terminated
                age_hours = (datetime.now(UTC) - orphan.created_at).total_seconds() / 3600
                effective_action = (
                    OrphanAction.TERMINATE if age_hours > self._max_orphan_age_hours else action
                )

                if effective_action == OrphanAction.ADOPT:
                    success = await self._adopt_orphan(orphan)
                    if success:
                        orphan.action_taken = OrphanAction.ADOPT
                        adopted += 1
                    else:
                        errors += 1

                elif effective_action == OrphanAction.TERMINATE:
                    success = await self._terminate_orphan(orphan)
                    if success:
                        orphan.action_taken = OrphanAction.TERMINATE
                        terminated += 1
                    else:
                        errors += 1

                else:  # IGNORE
                    orphan.action_taken = OrphanAction.IGNORE

            except Exception as e:
                logger.error(f"Error processing orphan {orphan.sandbox_id}: {e}")
                orphan.error_message = str(e)
                errors += 1

        duration = time.time() - start_time

        result = ReconciliationResult(
            discovered_orphans=len(orphans),
            adopted=adopted,
            terminated=terminated,
            errors=errors,
            orphan_containers=orphans,
            duration_seconds=duration,
        )

        logger.info(
            f"Reconciliation complete: {result.discovered_orphans} orphans found, "
            f"{result.adopted} adopted, {result.terminated} terminated, "
            f"{result.errors} errors in {result.duration_seconds:.2f}s"
        )

        return result

    async def discover_orphans(self) -> list[OrphanContainer]:
        """
        Discover orphan containers that are not tracked in memory.

        Returns:
            List of OrphanContainer objects
        """
        orphans = []

        try:
            loop = asyncio.get_event_loop()

            # Get all memstack sandbox containers
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,  # Include stopped containers
                    filters={"label": "memstack.sandbox=true"},
                ),
            )

            # Get set of tracked sandbox IDs
            tracked_ids = await self._get_tracked_sandbox_ids()

            for container in containers:
                labels = container.labels or {}
                sandbox_id = labels.get("memstack.sandbox.id", container.name)

                # Check if this container is already tracked
                if sandbox_id in tracked_ids:
                    continue

                # This is an orphan
                orphan = self._container_to_orphan(container)
                orphans.append(orphan)

                logger.info(
                    f"Discovered orphan container: {orphan.sandbox_id} "
                    f"(project_id={orphan.project_id}, status={orphan.status})"
                )

        except Exception as e:
            logger.error(f"Error discovering orphan containers: {e}")

        return orphans

    async def _get_tracked_sandbox_ids(self) -> set[str]:
        """Get set of sandbox IDs currently tracked in memory."""
        # Access the adapter's internal tracking
        if hasattr(self._adapter, "_active_sandboxes"):
            async with self._adapter._lock:
                return set(self._adapter._active_sandboxes.keys())
        return set()

    def _container_to_orphan(self, container) -> OrphanContainer:
        """Convert a Docker container to an OrphanContainer object."""
        labels = container.labels or {}

        # Parse creation time
        created_str = container.attrs.get("Created", "")
        try:
            # Docker timestamps are ISO 8601 with nanoseconds
            if "." in created_str:
                created_str = created_str.split(".")[0] + "Z"
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except Exception:
            created_at = datetime.now(UTC)

        # Extract port information
        ports = {}
        if labels.get("memstack.sandbox.mcp_port"):
            ports["mcp"] = int(labels["memstack.sandbox.mcp_port"])
        if labels.get("memstack.sandbox.desktop_port"):
            ports["desktop"] = int(labels["memstack.sandbox.desktop_port"])
        if labels.get("memstack.sandbox.terminal_port"):
            ports["terminal"] = int(labels["memstack.sandbox.terminal_port"])

        return OrphanContainer(
            container_id=container.id,
            container_name=container.name,
            sandbox_id=labels.get("memstack.sandbox.id", container.name),
            project_id=labels.get("memstack.project_id"),
            tenant_id=labels.get("memstack.tenant_id"),
            status=container.status,
            ports=ports,
            labels=labels,
            created_at=created_at,
        )

    async def _adopt_orphan(self, orphan: OrphanContainer) -> bool:
        """
        Adopt an orphan container into the tracking system.

        Args:
            orphan: The orphan container to adopt

        Returns:
            True if adoption was successful
        """
        try:
            # Only adopt running containers
            if orphan.status != "running":
                logger.info(f"Skipping adoption of non-running orphan: {orphan.sandbox_id}")
                return await self._terminate_orphan(orphan)

            # Use the adapter's sync_from_docker to adopt
            # This will add it to _active_sandboxes
            if hasattr(self._adapter, "sync_from_docker"):
                await self._adapter.sync_from_docker()

            # Verify adoption
            if hasattr(self._adapter, "_active_sandboxes"):
                async with self._adapter._lock:
                    if orphan.sandbox_id in self._adapter._active_sandboxes:
                        logger.info(f"Successfully adopted orphan: {orphan.sandbox_id}")

                        # Create database association if repository available
                        if self._repository and orphan.project_id:
                            await self._create_db_association(orphan)

                        return True

            logger.warning(f"Failed to adopt orphan: {orphan.sandbox_id}")
            return False

        except Exception as e:
            logger.error(f"Error adopting orphan {orphan.sandbox_id}: {e}")
            orphan.error_message = str(e)
            return False

    async def _terminate_orphan(self, orphan: OrphanContainer) -> bool:
        """
        Terminate an orphan container.

        Args:
            orphan: The orphan container to terminate

        Returns:
            True if termination was successful
        """
        try:
            loop = asyncio.get_event_loop()

            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(orphan.container_id),
            )

            # Stop if running
            if container.status == "running":
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: container.stop(timeout=5)),
                        timeout=15.0,
                    )
                except TimeoutError:
                    logger.warning(f"Stop timeout for orphan {orphan.sandbox_id}, killing")
                    await loop.run_in_executor(None, container.kill)

            # Remove container
            await loop.run_in_executor(None, lambda: container.remove(force=True))

            logger.info(f"Terminated orphan container: {orphan.sandbox_id}")
            return True

        except Exception as e:
            logger.error(f"Error terminating orphan {orphan.sandbox_id}: {e}")
            orphan.error_message = str(e)
            return False

    async def _create_db_association(self, orphan: OrphanContainer) -> None:
        """Create a database association for an adopted orphan."""
        if not self._repository or not orphan.project_id:
            return

        try:
            from src.domain.model.sandbox.project_sandbox import (
                ProjectSandbox,
                ProjectSandboxStatus,
            )

            # Check if association already exists
            existing = await self._repository.find_by_project(orphan.project_id)
            if existing:
                # Update existing association
                existing.sandbox_id = orphan.sandbox_id
                existing.status = ProjectSandboxStatus.ORPHAN  # Mark as adopted orphan
                existing.mark_accessed()
                await self._repository.save(existing)
                logger.info(f"Updated existing association for orphan: {orphan.sandbox_id}")
            else:
                # Create new association with ORPHAN status
                import uuid

                association = ProjectSandbox(
                    id=str(uuid.uuid4()),
                    project_id=orphan.project_id,
                    tenant_id=orphan.tenant_id or "unknown",
                    sandbox_id=orphan.sandbox_id,
                    status=ProjectSandboxStatus.ORPHAN,
                    created_at=orphan.created_at,
                    started_at=orphan.created_at,
                )
                await self._repository.save(association)
                logger.info(f"Created new association for orphan: {orphan.sandbox_id}")

        except Exception as e:
            logger.warning(f"Failed to create DB association for orphan {orphan.sandbox_id}: {e}")

    async def list_orphans(self) -> list[dict[str, Any]]:
        """
        List all current orphan containers for API/UI display.

        Returns:
            List of orphan information dictionaries
        """
        orphans = await self.discover_orphans()
        return [
            {
                "container_id": o.container_id,
                "container_name": o.container_name,
                "sandbox_id": o.sandbox_id,
                "project_id": o.project_id,
                "tenant_id": o.tenant_id,
                "status": o.status,
                "ports": o.ports,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "discovered_at": o.discovered_at.isoformat(),
            }
            for o in orphans
        ]

    async def adopt_orphan_by_id(
        self,
        container_id: str,
        project_id: str | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        """
        Manually adopt a specific orphan container.

        Args:
            container_id: Docker container ID or name
            project_id: Optional project ID to associate with
            tenant_id: Optional tenant ID to associate with

        Returns:
            True if adoption was successful
        """
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(container_id),
            )

            orphan = self._container_to_orphan(container)

            # Override project/tenant if provided
            if project_id:
                orphan.project_id = project_id
            if tenant_id:
                orphan.tenant_id = tenant_id

            return await self._adopt_orphan(orphan)

        except Exception as e:
            logger.error(f"Error adopting orphan by ID {container_id}: {e}")
            return False

    async def terminate_orphan_by_id(self, container_id: str) -> bool:
        """
        Manually terminate a specific orphan container.

        Args:
            container_id: Docker container ID or name

        Returns:
            True if termination was successful
        """
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(container_id),
            )

            orphan = self._container_to_orphan(container)
            return await self._terminate_orphan(orphan)

        except Exception as e:
            logger.error(f"Error terminating orphan by ID {container_id}: {e}")
            return False
