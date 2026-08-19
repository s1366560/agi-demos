"""Unit tests for agent HITL router safeguards."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.routers.agent import hitl as hitl_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import HITLResponseRequest
from src.infrastructure.agent.hitl import utils as hitl_utils


def _make_hitl_request(*, request_type: HITLRequestType) -> HITLRequest:
    metadata = {}
    if request_type == HITLRequestType.ENV_VAR:
        metadata = {
            "tool_name": "web_search",
            "fields": [{"name": "API_KEY", "label": "API Key", "required": False}],
        }
    return HITLRequest(
        id="req-1",
        request_type=request_type,
        conversation_id="conv-1",
        message_id="msg-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Need input",
        metadata=metadata,
        status=HITLRequestStatus.PENDING,
    )


def _set_hitl_encryption_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_ENCRYPTION_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_rejects_type_mismatch(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(
        return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    )
    publish_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    request = HITLResponseRequest(
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "ok"},
    )

    with pytest.raises(HTTPException, match="HITL type does not match request") as exc_info:
        await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
            request=request,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    publish_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_pending_hitl_requests_rejects_unauthorized_user(monkeypatch) -> None:
    conv_repo = MagicMock()
    conv_repo.find_by_id = AsyncMock(
        return_value=SimpleNamespace(id="conv-1", tenant_id="tenant-1", project_id="project-1")
    )

    monkeypatch.setattr(hitl_router, "SqlConversationRepository", lambda db: conv_repo)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=False))

    with pytest.raises(HTTPException, match="Access denied") as exc_info:
        await hitl_router.get_pending_hitl_requests(
            conversation_id="conv-1",
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_project_pending_hitl_requests_rejects_non_member(monkeypatch) -> None:
    monkeypatch.setattr(hitl_router, "_user_has_project_access", AsyncMock(return_value=False))

    with pytest.raises(HTTPException, match="Access denied") as exc_info:
        await hitl_router.get_project_pending_hitl_requests(
            project_id="project-1",
            current_user=SimpleNamespace(id="user-1", tenant_id="tenant-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
            limit=50,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_project_pending_hitl_requests_uses_injected_tenant_id(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_pending_by_project_for_user = AsyncMock(return_value=[])

    monkeypatch.setattr(hitl_router, "_user_has_project_access", AsyncMock(return_value=True))
    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)

    response = await hitl_router.get_project_pending_hitl_requests(
        project_id="project-1",
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=MagicMock(),
        limit=50,
    )

    assert response.total == 0
    repo.get_pending_by_project_for_user.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        limit=50,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_rejects_unauthorized_user(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(
        return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    )
    publish_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=False))

    request = HITLResponseRequest(
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
    )

    with pytest.raises(HTTPException, match="Access denied") as exc_info:
        await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
            request=request,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 403
    publish_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_rejects_non_target_user(monkeypatch) -> None:
    repo = MagicMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.user_id = "user-2"
    repo.get_by_id = AsyncMock(return_value=hitl_request)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(
        hitl_router,
        "_publish_hitl_response_to_redis",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    with pytest.raises(HTTPException, match="Access denied") as exc_info:
        await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
            request=HITLResponseRequest(
                request_id="req-1",
                hitl_type="env_var",
                response_data={"cancelled": True},
            ),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_authorized_pending_hitl_request_allows_target_user_with_project_access(
    monkeypatch,
) -> None:
    repo = MagicMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.user_id = "user-1"
    repo.get_by_id = AsyncMock(return_value=hitl_request)

    project_access = AsyncMock(return_value=True)
    conversation_access = AsyncMock(return_value=False)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(hitl_router, "_user_has_project_access", project_access)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", conversation_access)
    db = MagicMock()

    result = await hitl_router._load_authorized_pending_hitl_request(
        db=db,
        request_id="req-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )

    assert result is hitl_request
    project_access.assert_awaited_once_with(
        db=db,
        user_id="user-1",
        project_id="project-1",
    )
    conversation_access.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_rejects_invalid_env_var_shape(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(
        return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    )
    publish_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    request = HITLResponseRequest(
        request_id="req-1",
        hitl_type="env_var",
        response_data={"values": {"API_KEY": "value"}, "cancelled": True},
    )

    with pytest.raises(
        HTTPException,
        match="env_var responses must include exactly one of values/cancelled/timeout",
    ) as exc_info:
        await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
            request=request,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    publish_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_accepts_permission_metadata_type(monkeypatch) -> None:
    repo = MagicMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    hitl_request.metadata = {"hitl_type": "permission", "description": "Allow tool?"}
    repo.get_by_id = AsyncMock(return_value=hitl_request)
    repo.update_response = AsyncMock(return_value=hitl_request)
    repo.mark_completed = AsyncMock()
    publish_mock = AsyncMock(return_value=True)
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda session: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.validate_hitl_response",
        lambda **_: (True, None),
    )

    response = await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
        request=HITLResponseRequest(
            request_id="req-1",
            hitl_type="permission",
            response_data={"action": "allow", "granted": True, "scope": "once"},
        ),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.success is True
    assert response.message == "Permission response received"
    publish_mock.assert_awaited_once()
    assert publish_mock.await_args.kwargs["hitl_type"] == "permission"
    repo.update_response.assert_awaited_once()
    repo.mark_completed.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_reopens_pending_request_when_delivery_fails(monkeypatch) -> None:
    _set_hitl_encryption_env(monkeypatch)
    repo = MagicMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    repo.get_by_id = AsyncMock(return_value=hitl_request)
    repo.update_response = AsyncMock(return_value=hitl_request)
    publish_mock = AsyncMock(return_value=False)
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda session: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    response = await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
        request=HITLResponseRequest(
            request_id="req-1",
            hitl_type="env_var",
            response_data={"cancelled": True},
        ),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.success is True
    assert response.message == "Env Var response saved. Delivery is pending."
    repo.update_response.assert_awaited_once()
    assert db.commit.await_count == 1
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_rejects_expired_request(monkeypatch) -> None:
    repo = MagicMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    repo.get_by_id = AsyncMock(return_value=hitl_request)
    repo.mark_timeout = AsyncMock(return_value=hitl_request)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda db: repo)
    monkeypatch.setattr(
        hitl_router,
        "_publish_hitl_response_to_redis",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    response = await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
        request=HITLResponseRequest(
            request_id="req-1",
            hitl_type="env_var",
            response_data={"cancelled": True},
        ),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=SimpleNamespace(commit=AsyncMock()),
    )

    assert response.status_code == 410
    payload = json.loads(response.body)
    assert payload["detail"] == "HITL request has expired"
    assert payload["reason_code"] == "hitl_request_expired"
    assert payload["authority_revision"] == 2
    assert payload["authority_status"] == "timeout"
    assert payload["expires_at"] == hitl_request.expires_at.isoformat()
    repo.mark_timeout.assert_awaited_once_with("req-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_returns_authority_after_losing_atomic_claim(monkeypatch) -> None:
    pending = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    answered = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    answered.status = HITLRequestStatus.ANSWERED
    answered.answered_at = datetime.now(UTC)
    answered.response = "first answer"

    repo = MagicMock()
    repo.get_by_id = AsyncMock(side_effect=[pending, answered])
    repo.update_response = AsyncMock(return_value=None)
    publish_mock = AsyncMock(return_value=True)
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.validate_hitl_response",
        lambda **_: (True, None),
    )

    response = await hitl_router.respond_to_hitl(
            http_request=MagicMock(spec=Request),
        request=HITLResponseRequest(
            request_id="req-1",
            hitl_type="clarification",
            response_data={"answer": "second answer"},
        ),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["detail"] == "HITL request is no longer pending"
    assert payload["reason_code"] == "hitl_already_answered"
    assert payload["authority_revision"] == 2
    assert payload["authority_status"] == "answered"
    assert payload["answered_at"] == answered.answered_at.isoformat()
    publish_mock.assert_not_awaited()
    db.commit.assert_not_awaited()
