"""Integration tests for channel observability endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation


@pytest.mark.integration
@pytest.mark.asyncio
class TestChannelObservabilityEndpoints:
    """Integration tests for project-level channel observability APIs."""

    async def _seed_channel_data(
        self,
        db: AsyncSession,
        project_id: str,
        tenant_id: str,
        user_id: str,
    ) -> tuple[str, str]:
        config_id = str(uuid4())
        conversation_id = str(uuid4())

        config = ChannelConfigModel(
            id=config_id,
            project_id=project_id,
            channel_type="feishu",
            name="Test Feishu Channel",
            enabled=True,
            connection_mode="websocket",
            status="connected",
            created_by=user_id,
        )
        conversation = Conversation(
            id=conversation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Channel Conversation",
            status="active",
            meta={"channel_config_id": config_id},
            message_count=0,
        )
        binding = ChannelSessionBindingModel(
            id=str(uuid4()),
            project_id=project_id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            channel_type="feishu",
            chat_id="chat-1",
            chat_type="group",
            thread_id="thread-1",
            topic_id="topic-1",
            session_key=f"project:{project_id}:channel:feishu:config:{config_id}:group:chat-1:topic:topic-1:thread:thread-1",
        )
        pending_outbox = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=project_id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="pending message",
            status="pending",
            attempt_count=0,
            max_attempts=3,
        )
        failed_outbox = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=project_id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="failed message",
            status="failed",
            attempt_count=1,
            max_attempts=3,
            last_error="delivery failed",
        )

        db.add(config)
        db.add(conversation)
        db.add(binding)
        db.add(pending_outbox)
        db.add(failed_outbox)
        await db.commit()
        return config_id, conversation_id

    async def test_summary_endpoint_returns_counts(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Summary endpoint should include binding and outbox status counts."""
        await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/summary"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == test_project_db.id
        assert data["session_bindings_total"] == 1
        assert data["outbox_total"] == 2
        assert data["outbox_by_status"]["pending"] == 1
        assert data["outbox_by_status"]["failed"] == 1
        assert data["latest_delivery_error"] == "delivery failed"

    async def test_outbox_endpoint_filters_by_status(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Outbox endpoint should filter by status."""
        await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/outbox?status=failed"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "failed"
        assert data["items"][0]["last_error"] == "delivery failed"

    async def test_outbox_endpoint_rejects_invalid_status(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Outbox endpoint should validate status filter values."""
        await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/outbox?status=typo"
        )
        assert response.status_code == 422

    async def test_session_bindings_endpoint_lists_bindings(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Session binding endpoint should return deterministic session bindings."""
        config_id, conversation_id = await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/session-bindings"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["channel_config_id"] == config_id
        assert data["items"][0]["conversation_id"] == conversation_id
        assert "session_key" in data["items"][0]

    async def test_summary_endpoint_uses_most_recent_error_update_time(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Summary latest_delivery_error should prefer most recently updated failure."""
        config_id, conversation_id = await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        base = datetime.now(timezone.utc)
        latest_by_update = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=test_project_db.id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="older created but newer updated",
            status="failed",
            attempt_count=2,
            max_attempts=3,
            last_error="latest-by-updated",
            created_at=base,
            updated_at=base + timedelta(minutes=10),
        )
        latest_by_created = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=test_project_db.id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="newer created but older updated",
            status="failed",
            attempt_count=1,
            max_attempts=3,
            last_error="latest-by-created",
            created_at=base + timedelta(minutes=20),
            updated_at=base + timedelta(minutes=1),
        )
        test_db.add(latest_by_update)
        test_db.add(latest_by_created)
        await test_db.commit()

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/summary"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["latest_delivery_error"] == "latest-by-updated"

    async def test_summary_endpoint_ignores_null_updated_at_when_newer_updated_exists(
        self,
        authenticated_async_client: AsyncClient,
        test_db: AsyncSession,
        test_project_db,
        test_user,
    ):
        """Summary should prefer non-null latest updated_at over null updated_at rows."""
        config_id, conversation_id = await self._seed_channel_data(
            test_db,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

        base = datetime.now(timezone.utc)
        null_updated = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=test_project_db.id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="null updated",
            status="failed",
            attempt_count=1,
            max_attempts=3,
            last_error="null-updated-error",
            created_at=base + timedelta(minutes=30),
            updated_at=None,
        )
        newer_updated = ChannelOutboxModel(
            id=str(uuid4()),
            project_id=test_project_db.id,
            channel_config_id=config_id,
            conversation_id=conversation_id,
            chat_id="chat-1",
            content_text="has updated",
            status="failed",
            attempt_count=1,
            max_attempts=3,
            last_error="newer-updated-error",
            created_at=base,
            updated_at=base + timedelta(minutes=20),
        )
        test_db.add(null_updated)
        test_db.add(newer_updated)
        await test_db.commit()

        response = await authenticated_async_client.get(
            f"/api/v1/channels/projects/{test_project_db.id}/observability/summary"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["latest_delivery_error"] == "newer-updated-error"
