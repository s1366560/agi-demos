"""Unit tests for instance channel connection checks."""

from unittest.mock import AsyncMock

import pytest

from src.application.services.instance_channel_service import InstanceChannelService
from src.domain.model.instance.instance_channel import InstanceChannelConfig


@pytest.mark.unit
class TestInstanceChannelConnectionTest:
    """Connection checks should persist real observed status instead of blind success."""

    async def test_webhook_connection_success_marks_channel_connected(self, monkeypatch) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="webhook",
            name="Webhook",
            config={"url": "https://example.com/webhook"},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        async def fake_http_endpoint(self, url, *, label, timeout, headers=None):
            assert url == "https://example.com/webhook"
            assert label == "Webhook endpoint"
            assert timeout == 10.0
            assert headers is None
            return "Webhook endpoint reachable (HTTP 204)"

        monkeypatch.setattr(
            InstanceChannelService,
            "_test_http_endpoint",
            fake_http_endpoint,
        )

        service = InstanceChannelService(repo)
        result = await service.test_connection("channel-1")

        assert result == {
            "status": "ok",
            "message": "Webhook endpoint reachable (HTTP 204)",
        }
        assert entity.status == "connected"
        assert entity.last_connected_at is not None
        assert entity.updated_at == entity.last_connected_at
        repo.update.assert_awaited_once_with(entity)

    async def test_missing_required_config_marks_channel_error(self) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="webhook",
            name="Webhook",
            config={},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        service = InstanceChannelService(repo)
        result = await service.test_connection("channel-1")

        assert result == {
            "status": "error",
            "message": "Missing required config field: url",
        }
        assert entity.status == "error"
        assert entity.last_connected_at is None
        assert entity.updated_at is not None
        repo.update.assert_awaited_once_with(entity)

    async def test_unsupported_channel_type_marks_channel_error(self) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="slack",
            name="Slack",
            config={},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        service = InstanceChannelService(repo)
        result = await service.test_connection("channel-1")

        assert result == {
            "status": "error",
            "message": "Connection testing is not supported for slack channels",
        }
        assert entity.status == "error"
        repo.update.assert_awaited_once_with(entity)

    async def test_missing_channel_raises_value_error(self) -> None:
        repo = AsyncMock()
        repo.find_by_id.return_value = None

        service = InstanceChannelService(repo)

        with pytest.raises(ValueError, match="Channel not found"):
            await service.test_connection("missing")

    async def test_update_rejects_channel_from_different_instance(self) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="webhook",
            name="Webhook",
            config={},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        service = InstanceChannelService(repo)

        with pytest.raises(ValueError, match="Channel not found"):
            await service.update_channel(
                "channel-1",
                expected_instance_id="instance-2",
                name="Renamed",
            )

        repo.update.assert_not_awaited()

    async def test_delete_rejects_channel_from_different_instance(self) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="webhook",
            name="Webhook",
            config={},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        service = InstanceChannelService(repo)

        with pytest.raises(ValueError, match="Channel not found"):
            await service.delete_channel("channel-1", expected_instance_id="instance-2")

        repo.delete.assert_not_awaited()

    async def test_connection_rejects_channel_from_different_instance(self) -> None:
        entity = InstanceChannelConfig(
            id="channel-1",
            instance_id="instance-1",
            channel_type="webhook",
            name="Webhook",
            config={"url": "https://example.com/webhook"},
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = entity

        service = InstanceChannelService(repo)

        with pytest.raises(ValueError, match="Channel not found"):
            await service.test_connection("channel-1", expected_instance_id="instance-2")

        repo.update.assert_not_awaited()
