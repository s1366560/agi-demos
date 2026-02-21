"""Tests for HITLChannelResponder."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.services.channels.hitl_responder import HITLChannelResponder

DB_FACTORY_PATH = (
    "src.infrastructure.adapters.secondary.persistence.database.async_session_factory"
)
HITL_REPO_PATH = (
    "src.infrastructure.adapters.secondary.persistence."
    "sql_hitl_request_repository.SqlHITLRequestRepository"
)
SETTINGS_PATH = "src.configuration.config.get_settings"


@pytest.fixture
def responder() -> HITLChannelResponder:
    return HITLChannelResponder()


@pytest.mark.unit
class TestHITLChannelResponder:
    async def test_respond_request_not_found(self, responder: HITLChannelResponder) -> None:
        """Returns False if HITL request not found in DB."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(DB_FACTORY_PATH, return_value=mock_ctx), patch(
            HITL_REPO_PATH, return_value=mock_repo
        ):
            result = await responder.respond(
                request_id="missing-id",
                hitl_type="clarification",
                response_data={"answer": "test"},
            )

        assert result is False
        mock_repo.get_by_id.assert_awaited_once_with("missing-id")

    async def test_respond_already_resolved(self, responder: HITLChannelResponder) -> None:
        """Returns False if HITL request already resolved."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = MagicMock()
        mock_request.status = "resolved"
        mock_repo.get_by_id.return_value = mock_request

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(DB_FACTORY_PATH, return_value=mock_ctx), patch(
            HITL_REPO_PATH, return_value=mock_repo
        ):
            result = await responder.respond(
                request_id="resolved-id",
                hitl_type="clarification",
                response_data={"answer": "test"},
            )

        assert result is False

    async def test_respond_publishes_to_redis(self, responder: HITLChannelResponder) -> None:
        """Successful response publishes to Redis stream."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = MagicMock()
        mock_request.status = "pending"
        mock_request.tenant_id = "t-1"
        mock_request.project_id = "p-1"
        mock_repo.get_by_id.return_value = mock_request

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(DB_FACTORY_PATH, return_value=mock_ctx), patch(
            HITL_REPO_PATH, return_value=mock_repo
        ), patch(SETTINGS_PATH) as mock_settings, patch(
            "redis.asyncio.from_url", return_value=mock_redis
        ):
            mock_settings.return_value.REDIS_HOST = "localhost"
            mock_settings.return_value.REDIS_PORT = 6379

            result = await responder.respond(
                request_id="req-1",
                hitl_type="decision",
                response_data={"answer": "approve"},
                responder_id="user-123",
            )

        assert result is True
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "hitl:response:t-1:p-1"
        payload = call_args[0][1]
        assert payload["request_id"] == "req-1"
        assert payload["source"] == "channel"
        assert payload["responder_id"] == "user-123"

    async def test_respond_handles_exception_gracefully(
        self, responder: HITLChannelResponder
    ) -> None:
        """Returns False on unexpected error."""
        with patch(
            DB_FACTORY_PATH,
            side_effect=Exception("DB down"),
        ):
            result = await responder.respond(
                request_id="req-x",
                hitl_type="clarification",
                response_data={},
            )
        assert result is False
