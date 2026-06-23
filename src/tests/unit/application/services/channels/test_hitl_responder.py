"""Tests for HITLChannelResponder."""

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.channels.hitl_responder import (
    HITLChannelResponder,
    HITLChannelResponseOutcome,
)

DB_FACTORY_PATH = "src.infrastructure.adapters.secondary.persistence.database.async_session_factory"
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
    async def test_respond_claims_and_publishes_with_tenant_project_hints(
        self, responder: HITLChannelResponder
    ) -> None:
        """Tenant/project hints must still go through DB claim + publish flow."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-direct",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="clarification"),
            question="Need input",
            options=[],
            context={},
            metadata={},
        )
        mock_repo.get_by_id.return_value = mock_request
        mock_repo.update_response = AsyncMock(return_value=mock_request)

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock()
        mock_redis.aclose = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "user-1"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
            patch(SETTINGS_PATH) as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            mock_settings.return_value.redis_host = "localhost"
            mock_settings.return_value.redis_port = 6379

            result = await responder.respond(
                request_id="req-direct",
                hitl_type="clarification",
                response_data={"answer": "test"},
                tenant_id="t-1",
                project_id="p-1",
                responder_id="user-1",
            )

        assert result is HITLChannelResponseOutcome.QUEUED
        mock_repo.update_response.assert_awaited_once()
        assert mock_session.commit.await_count == 1
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "hitl:response:t-1:p-1"
        envelope = call_args[0][1]
        assert "data" in envelope
        payload = json.loads(envelope["data"])
        assert payload["request_id"] == "req-direct"
        assert payload["source"] == "channel"
        assert payload["conversation_id"] == "conv-1"
        assert payload["message_id"] == "msg-1"

    async def test_respond_request_not_found(self, responder: HITLChannelResponder) -> None:
        """Returns False if HITL request not found in DB."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock()

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
        ):
            result = await responder.respond(
                request_id="missing-id",
                hitl_type="clarification",
                response_data={"answer": "test"},
            )

        assert result is HITLChannelResponseOutcome.REJECTED
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
        mock_session.get = AsyncMock()

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
        ):
            result = await responder.respond(
                request_id="resolved-id",
                hitl_type="clarification",
                response_data={"answer": "test"},
            )

        assert result is HITLChannelResponseOutcome.REJECTED

    async def test_respond_publishes_to_redis(self, responder: HITLChannelResponder) -> None:
        """Publish failure keeps the answered request pending recovery instead of reopening."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-1",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="decision"),
            question="Approve?",
            options=["approve", "deny"],
            context={},
            metadata={},
        )
        mock_repo.get_by_id.return_value = mock_request
        mock_repo.update_response = AsyncMock(return_value=mock_request)

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=RuntimeError("redis down"))
        mock_redis.aclose = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "user-123"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
            patch(SETTINGS_PATH) as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            mock_settings.return_value.redis_host = "localhost"
            mock_settings.return_value.redis_port = 6379

            result = await responder.respond(
                request_id="req-1",
                hitl_type="decision",
                response_data={"decision": "approve"},
                responder_id="user-123",
            )

        assert result is HITLChannelResponseOutcome.DELIVERY_PENDING
        mock_repo.update_response.assert_awaited_once()
        assert mock_session.commit.await_count == 1
        mock_redis.xadd.assert_awaited_once()

    async def test_publish_to_redis_failure_log_omits_identifiers(
        self,
        responder: HITLChannelResponder,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Redis publish failure logs should not echo request IDs or exception details."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(
            side_effect=RuntimeError("redis down for secret-request-id")
        )
        mock_redis.aclose = AsyncMock()
        caplog.set_level(
            logging.ERROR,
            logger="src.application.services.channels.hitl_responder",
        )

        with (
            patch(SETTINGS_PATH) as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            mock_settings.return_value.redis_host = "localhost"
            mock_settings.return_value.redis_port = 6379

            result = await responder._publish_to_redis(
                request_id="secret-request-id",
                hitl_type="decision",
                response_data={"decision": "approve"},
                tenant_id="tenant-secret",
                project_id="project-secret",
                conversation_id="conversation-secret",
                message_id="message-secret",
                responder_id="responder-secret",
            )

        assert result is False
        mock_redis.xadd.assert_awaited_once()
        assert "secret-request-id" not in caplog.text
        assert "tenant-secret" not in caplog.text
        assert "redis down" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

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
        assert result is HITLChannelResponseOutcome.REJECTED

    async def test_respond_does_not_reopen_when_publish_succeeds_but_close_fails(
        self, responder: HITLChannelResponder
    ) -> None:
        """aclose failures after a successful publish must not reopen the request."""
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-close",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="clarification"),
            question="Need input",
            options=[],
            context={},
            metadata={},
        )
        mock_repo.get_by_id.return_value = mock_request
        mock_repo.update_response = AsyncMock(return_value=mock_request)

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock()
        mock_redis.aclose = AsyncMock(side_effect=RuntimeError("close failed"))

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "user-1"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
            patch(SETTINGS_PATH) as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            mock_settings.return_value.redis_host = "localhost"
            mock_settings.return_value.redis_port = 6379

            result = await responder.respond(
                request_id="req-close",
                hitl_type="clarification",
                response_data={"answer": "ok"},
                responder_id="user-1",
            )

        assert result is HITLChannelResponseOutcome.QUEUED
        assert mock_session.commit.await_count == 1
        mock_redis.xadd.assert_awaited_once()

    async def test_respond_rejects_unauthorized_channel_responder(
        self, responder: HITLChannelResponder
    ) -> None:
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-auth",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="clarification"),
            question="Need input",
            options=[],
            context={},
            metadata={},
        )
        mock_repo.get_by_id.return_value = mock_request

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "owner-1"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
        ):
            result = await responder.respond(
                request_id="req-auth",
                hitl_type="clarification",
                response_data={"answer": "ok"},
                responder_id="intruder-1",
            )

        assert result is HITLChannelResponseOutcome.REJECTED
        mock_repo.update_response.assert_not_awaited()

    async def test_respond_prefers_request_user_binding(
        self, responder: HITLChannelResponder
    ) -> None:
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-bound-user",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="clarification"),
            question="Need input",
            options=[],
            context={},
            metadata={},
            user_id="owner-1",
            expires_at=None,
        )
        mock_repo.get_by_id.return_value = mock_request
        mock_repo.update_response = AsyncMock(return_value=mock_request)
        mock_repo.get_encryption_service = AsyncMock(return_value=None)
        mock_repo.claim_for_processing = AsyncMock(return_value=mock_request)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "other-user"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
            patch(
                "src.application.services.channels.hitl_responder.HITLChannelResponder._publish_to_redis",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await responder.respond(
                request_id="req-bound-user",
                hitl_type="clarification",
                response_data={"answer": "ok"},
                responder_id="owner-1",
            )

        assert result is HITLChannelResponseOutcome.QUEUED
        mock_session.get.assert_not_awaited()

    async def test_respond_rejects_expired_request(self, responder: HITLChannelResponder) -> None:
        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_request = SimpleNamespace(
            id="req-expired",
            status="pending",
            tenant_id="t-1",
            project_id="p-1",
            conversation_id="conv-1",
            message_id="msg-1",
            request_type=SimpleNamespace(value="clarification"),
            question="Need input",
            options=[],
            context={},
            metadata={},
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        mock_repo.get_by_id.return_value = mock_request
        mock_repo.mark_timeout = AsyncMock(return_value=mock_request)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=SimpleNamespace(meta={"sender_id": "user-1"}))

        with (
            patch(DB_FACTORY_PATH, return_value=mock_ctx),
            patch(HITL_REPO_PATH, return_value=mock_repo),
        ):
            result = await responder.respond(
                request_id="req-expired",
                hitl_type="clarification",
                response_data={"answer": "ok"},
                responder_id="user-1",
            )

        assert result is HITLChannelResponseOutcome.REJECTED
        mock_repo.mark_timeout.assert_awaited_once_with("req-expired")
        mock_repo.update_response.assert_not_awaited()
