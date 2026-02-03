"""Sandbox Status Sync Service.

Handles the synchronization between Docker container state and database state,
and publishes SSE events for real-time frontend updates.
"""

import logging
from typing import Optional

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.domain.model.sandbox.project_sandbox import ProjectSandboxStatus
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)

logger = logging.getLogger(__name__)


# Map Docker status to domain status
DOCKER_TO_DOMAIN_STATUS = {
    "running": ProjectSandboxStatus.RUNNING,
    "stopped": ProjectSandboxStatus.STOPPED,
    "error": ProjectSandboxStatus.ERROR,
    "terminated": ProjectSandboxStatus.TERMINATED,
    "creating": ProjectSandboxStatus.CREATING,
}


class SandboxStatusSyncService:
    """Service for syncing sandbox status between Docker and database.
    
    When Docker events are received:
    1. Updates the database record with new status
    2. Publishes SSE event for frontend real-time update
    """
    
    def __init__(
        self,
        session_factory,
        event_publisher: Optional[SandboxEventPublisher] = None,
    ):
        """Initialize the service.
        
        Args:
            session_factory: SQLAlchemy async session factory
            event_publisher: Optional event publisher for SSE
        """
        self._session_factory = session_factory
        self._event_publisher = event_publisher
        
    async def handle_status_change(
        self,
        project_id: str,
        sandbox_id: str,
        new_status: str,
        event_type: str,
    ) -> bool:
        """Handle a container status change event.
        
        Args:
            project_id: Project ID
            sandbox_id: Sandbox container ID/name
            new_status: New status string (running, stopped, error, terminated)
            event_type: Docker event type (start, stop, die, kill, oom, etc.)
            
        Returns:
            True if status was updated successfully
        """
        logger.info(
            f"[SandboxStatusSync] Handling status change: "
            f"project={project_id}, sandbox={sandbox_id}, "
            f"status={new_status}, event={event_type}"
        )
        
        # Map to domain status
        domain_status = DOCKER_TO_DOMAIN_STATUS.get(new_status)
        if not domain_status:
            logger.warning(f"[SandboxStatusSync] Unknown status: {new_status}")
            return False
            
        # Update database
        try:
            async with self._session_factory() as session:
                repository = SqlProjectSandboxRepository(session)
                
                # Find by project ID
                association = await repository.find_by_project(project_id)
                if not association:
                    logger.warning(
                        f"[SandboxStatusSync] No association found for project {project_id}"
                    )
                    return False
                    
                # Check if status actually changed
                if association.status == domain_status:
                    logger.debug(
                        f"[SandboxStatusSync] Status unchanged for {sandbox_id}"
                    )
                    return True
                    
                # Update status based on event
                old_status = association.status
                
                if domain_status == ProjectSandboxStatus.RUNNING:
                    association.mark_healthy()
                elif domain_status == ProjectSandboxStatus.STOPPED:
                    association.mark_stopped()
                elif domain_status == ProjectSandboxStatus.ERROR:
                    association.mark_error(f"Container event: {event_type}")
                elif domain_status == ProjectSandboxStatus.TERMINATED:
                    association.mark_terminated()
                    
                await repository.save(association)
                
                logger.info(
                    f"[SandboxStatusSync] Updated status: {old_status.value} -> "
                    f"{domain_status.value} for sandbox {sandbox_id}"
                )
                
        except Exception as e:
            logger.error(f"[SandboxStatusSync] Database update error: {e}")
            return False
            
        # Publish SSE event
        if self._event_publisher:
            try:
                await self._event_publisher.publish_sandbox_status(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    status=domain_status.value,
                )
                logger.debug(
                    f"[SandboxStatusSync] Published SSE event for {sandbox_id}"
                )
            except Exception as e:
                logger.warning(f"[SandboxStatusSync] Failed to publish SSE event: {e}")
                
        return True
