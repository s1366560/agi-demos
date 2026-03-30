"""
DeployService: Business logic for deployment management.

This service handles deployment lifecycle operations including
creating, tracking, and completing deployments against instances.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from src.domain.model.deploy.deploy_record import DeployRecord
from src.domain.model.deploy.enums import DeployAction, DeployStatus
from src.domain.model.instance.enums import InstanceStatus
from src.domain.ports.repositories.deploy_record_repository import (
    DeployRecordRepository,
)
from src.domain.ports.repositories.instance_repository import (
    InstanceRepository,
)

logger = logging.getLogger(__name__)


class DeployService:
    """Service for managing deployment lifecycle."""

    def __init__(
        self,
        deploy_record_repo: DeployRecordRepository,
        instance_repo: InstanceRepository,
        redis_client: redis.Redis | None = None,
    ) -> None:
        self._deploy_record_repo = deploy_record_repo
        self._instance_repo = instance_repo
        self._redis_client = redis_client

    async def _publish_progress(self, deploy_id: str, status: str, *, is_terminal: bool) -> None:
        if self._redis_client is None:
            return
        event_type = "done" if is_terminal else "status"
        event = json.dumps({"type": event_type, "status": status, "deploy_id": deploy_id})
        try:
            await self._redis_client.publish(f"deploy:progress:{deploy_id}", event)
        except Exception:
            logger.warning("Failed to publish deploy progress for %s", deploy_id)

    async def create_deploy(
        self,
        instance_id: str,
        action: DeployAction,
        triggered_by: str,
        image_version: str | None = None,
        replicas: int | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> DeployRecord:
        """
        Create a new deployment record for an instance.

        Args:
            instance_id: Target instance ID.
            action: Deployment action to perform.
            triggered_by: User ID who triggered the deploy.
            image_version: Container image version (optional).
            replicas: Desired replica count (optional).
            config_snapshot: Configuration snapshot (optional).

        Returns:
            Created deploy record.

        Raises:
            ValueError: If instance does not exist or is not deployable.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")
        if not instance.is_deployable():
            raise ValueError(
                f"Instance {instance_id} is not deployable (status={instance.status.value})"
            )

        # Compute next revision number
        next_revision = instance.current_revision + 1

        record = DeployRecord(
            id=DeployRecord.generate_id(),
            instance_id=instance_id,
            revision=next_revision,
            action=action,
            image_version=image_version,
            replicas=replicas,
            config_snapshot=config_snapshot or {},
            status=DeployStatus.pending,
            triggered_by=triggered_by,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )

        # Transition instance to deploying
        instance.status = InstanceStatus.deploying
        instance.current_revision = next_revision
        instance.updated_at = datetime.now(UTC)

        await self._deploy_record_repo.save(record)
        await self._instance_repo.save(instance)
        logger.info(f"Created deploy {record.id} (rev {next_revision}) for instance {instance_id}")
        await self._publish_progress(record.id, DeployStatus.pending.value, is_terminal=False)
        return record

    async def get_deploy(self, deploy_id: str) -> DeployRecord | None:
        """
        Retrieve a deploy record by ID.

        Args:
            deploy_id: Deploy record ID.

        Returns:
            DeployRecord if found, None otherwise.
        """
        return await self._deploy_record_repo.find_by_id(deploy_id)

    async def list_deploys(
        self,
        instance_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DeployRecord]:
        """
        List deploy records for an instance.

        Args:
            instance_id: Instance ID to filter by.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of deploy records.
        """
        return await self._deploy_record_repo.find_by_instance(
            instance_id, limit=limit, offset=offset
        )

    async def mark_deploy_success(
        self,
        deploy_id: str,
        message: str | None = None,
    ) -> DeployRecord:
        """
        Mark a deployment as successful.

        Updates the deploy record status and transitions the target
        instance to running.

        Args:
            deploy_id: Deploy record ID.
            message: Optional success message.

        Returns:
            Updated deploy record.

        Raises:
            ValueError: If deploy record or instance not found.
        """
        record = await self._deploy_record_repo.find_by_id(deploy_id)
        if not record:
            raise ValueError(f"Deploy record {deploy_id} not found")

        record.mark_success(message)

        instance = await self._instance_repo.find_by_id(record.instance_id)
        if not instance:
            raise ValueError(f"Instance {record.instance_id} not found")

        instance.status = InstanceStatus.running
        instance.updated_at = datetime.now(UTC)

        await self._deploy_record_repo.save(record)
        await self._instance_repo.save(instance)
        logger.info(f"Deploy {deploy_id} marked success")
        await self._publish_progress(deploy_id, record.status.value, is_terminal=True)
        return record

    async def mark_deploy_failed(self, deploy_id: str, message: str) -> DeployRecord:
        """
        Mark a deployment as failed.

        Updates the deploy record status and transitions the target
        instance to error.

        Args:
            deploy_id: Deploy record ID.
            message: Error message describing the failure.

        Returns:
            Updated deploy record.

        Raises:
            ValueError: If deploy record or instance not found.
        """
        record = await self._deploy_record_repo.find_by_id(deploy_id)
        if not record:
            raise ValueError(f"Deploy record {deploy_id} not found")

        record.mark_failed(message)

        instance = await self._instance_repo.find_by_id(record.instance_id)
        if not instance:
            raise ValueError(f"Instance {record.instance_id} not found")

        instance.status = InstanceStatus.error
        instance.updated_at = datetime.now(UTC)

        await self._deploy_record_repo.save(record)
        await self._instance_repo.save(instance)
        logger.info(f"Deploy {deploy_id} marked failed: {message}")
        await self._publish_progress(deploy_id, record.status.value, is_terminal=True)
        return record

    async def cancel_deploy(self, deploy_id: str) -> DeployRecord:
        """
        Cancel a deployment that has not yet reached a terminal state.

        Args:
            deploy_id: Deploy record ID.

        Returns:
            Updated deploy record.

        Raises:
            ValueError: If deploy record not found or already terminal.
        """
        record = await self._deploy_record_repo.find_by_id(deploy_id)
        if not record:
            raise ValueError(f"Deploy record {deploy_id} not found")

        if record.is_terminal():
            raise ValueError(
                f"Deploy {deploy_id} is already terminal (status={record.status.value})"
            )

        record.mark_cancelled()

        await self._deploy_record_repo.save(record)
        logger.info(f"Deploy {deploy_id} cancelled")
        await self._publish_progress(deploy_id, record.status.value, is_terminal=True)
        return record

    async def get_latest_deploy(self, instance_id: str) -> DeployRecord | None:
        """
        Get the most recent deploy record for an instance.

        Args:
            instance_id: Instance ID.

        Returns:
            Latest DeployRecord if any exist, None otherwise.
        """
        records = await self._deploy_record_repo.find_by_instance(instance_id, limit=1, offset=0)
        return records[0] if records else None
