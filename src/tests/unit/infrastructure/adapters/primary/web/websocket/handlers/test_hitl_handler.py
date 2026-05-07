"""Unit tests for WebSocket HITL handler safeguards."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.websocket.handlers import hitl_handler
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.agent.hitl import utils as hitl_utils


def _make_context() -> MessageContext:
    websocket = SimpleNamespace(send_json=AsyncMock())
    return MessageContext(
        websocket=websocket,
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        db=MagicMock(),
        container=MagicMock(),
    )


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
async def test_handle_hitl_response_rejects_type_mismatch(monkeypatch) -> None:
    context = _make_context()
    publish_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)),
    )
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "ok"},
        ack_type="clarification_response_ack",
    )

    context.websocket.send_json.assert_awaited_once()
    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert payload["data"]["message"] == "HITL type does not match request"
    publish_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_rejects_unauthorized_user(monkeypatch) -> None:
    context = _make_context()
    publish_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)),
    )
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=False))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
        ack_type="env_var_response_ack",
    )

    context.websocket.send_json.assert_awaited_once()
    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert payload["data"]["message"] == "Access denied"
    publish_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_rejects_non_target_user(monkeypatch) -> None:
    context = _make_context()
    publish_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.user_id = "user-2"

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=hitl_request),
    )
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
        ack_type="env_var_response_ack",
    )

    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert payload["data"]["message"] == "Access denied"
    publish_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_authorized_pending_hitl_request_allows_target_user_with_project_access(
    monkeypatch,
) -> None:
    context = _make_context()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.user_id = "user-1"

    project_access = AsyncMock(return_value=True)
    conversation_access = AsyncMock(return_value=False)

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=hitl_request),
    )
    monkeypatch.setattr(hitl_handler, "_user_has_project_access", project_access)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", conversation_access)

    result = await hitl_handler._load_authorized_pending_hitl_request(
        context=context,
        request_id="req-1",
    )

    assert result is hitl_request
    project_access.assert_awaited_once_with(
        user_id="user-1",
        project_id="project-1",
        session_factory=None,
    )
    conversation_access.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_accepts_permission_metadata_type(monkeypatch) -> None:
    context = _make_context()
    publish_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()
    bridge_mock = AsyncMock()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    hitl_request.metadata = {"hitl_type": "permission", "description": "Allow tool?"}

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=hitl_request),
    )
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_start_hitl_stream_bridge", bridge_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.validate_hitl_response",
        lambda **_: (True, None),
    )

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="permission",
        response_data={"action": "allow", "granted": True},
        ack_type="permission_response_ack",
    )

    publish_mock.assert_awaited_once()
    assert publish_mock.await_args.kwargs["hitl_type"] == "permission"
    persist_mock.assert_awaited_once()
    bridge_mock.assert_awaited_once_with(context=context, request_id="req-1")
    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "permission_response_ack"
    assert payload["success"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_rejects_invalid_env_var_shape(monkeypatch) -> None:
    context = _make_context()
    publish_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=_make_hitl_request(request_type=HITLRequestType.ENV_VAR)),
    )
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"values": {"API_KEY": "value"}, "cancelled": True},
        ack_type="env_var_response_ack",
    )

    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert (
        payload["data"]["message"]
        == "env_var responses must include exactly one of values/cancelled/timeout"
    )
    publish_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_claims_before_publish(monkeypatch) -> None:
    _set_hitl_encryption_env(monkeypatch)
    context = _make_context()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    call_order: list[str] = []

    async def persist_response(**_: object) -> None:
        call_order.append("persist")

    async def publish_response(**_: object) -> bool:
        call_order.append("publish")
        return False

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=hitl_request),
    )
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_response)
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_response)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
        ack_type="env_var_response_ack",
    )

    assert call_order == ["persist", "publish"]
    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "env_var_response_ack"
    assert payload["success"] is True
    assert payload["delivery_pending"] is True
    get_settings.cache_clear()
    monkeypatch.setattr(hitl_utils, "_hitl_stream_encryption_service", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_respond_handler_accepts_cancelled_envelope(monkeypatch) -> None:
    context = _make_context()
    handle_mock = AsyncMock()

    monkeypatch.setattr(hitl_handler, "_handle_hitl_response", handle_mock)

    await hitl_handler.EnvVarRespondHandler().handle(
        context,
        {"request_id": "req-1", "cancelled": True},
    )

    handle_mock.assert_awaited_once_with(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
        ack_type="env_var_response_ack",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_rejects_expired_request(monkeypatch) -> None:
    context = _make_context()
    hitl_request = _make_hitl_request(request_type=HITLRequestType.ENV_VAR)
    hitl_request.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=hitl_request),
    )
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", AsyncMock())
    monkeypatch.setattr(
        hitl_handler,
        "_publish_hitl_response_to_redis",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(hitl_handler, "_mark_hitl_timeout", AsyncMock(return_value=True))
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="env_var",
        response_data={"cancelled": True},
        ack_type="env_var_response_ack",
    )

    hitl_handler._mark_hitl_timeout.assert_awaited_once_with("req-1", session_factory=None)
    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert payload["data"]["message"] == "HITL request req-1 has expired (status: timeout)"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_threads_injected_session_factory(monkeypatch) -> None:
    """P2-18: helpers must receive the injected sessionmaker from MessageContext."""
    sentinel_factory = MagicMock(name="sentinel_session_factory")
    websocket = SimpleNamespace(send_json=AsyncMock())
    context = MessageContext(
        websocket=websocket,
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        db=MagicMock(),
        container=MagicMock(),
        session_factory=sentinel_factory,
    )

    hitl_request = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)

    load_mock = AsyncMock(return_value=hitl_request)
    access_mock = AsyncMock(return_value=True)
    persist_mock = AsyncMock()
    publish_mock = AsyncMock(return_value=True)
    bridge_mock = AsyncMock()

    monkeypatch.setattr(hitl_handler, "_load_hitl_request", load_mock)
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", access_mock)
    monkeypatch.setattr(hitl_handler, "_persist_hitl_response", persist_mock)
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)
    monkeypatch.setattr(hitl_handler, "_start_hitl_stream_bridge", bridge_mock)

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "ok"},
        ack_type="clarification_response_ack",
    )

    load_mock.assert_awaited_once_with("req-1", session_factory=sentinel_factory)
    access_kwargs = access_mock.await_args.kwargs
    assert access_kwargs["session_factory"] is sentinel_factory
    persist_kwargs = persist_mock.await_args.kwargs
    assert persist_kwargs["session_factory"] is sentinel_factory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_session_factory_warns_once_when_falling_back(monkeypatch, caplog) -> None:
    """P2-18: missing factory triggers exactly one deprecation warning."""
    monkeypatch.setattr(hitl_handler, "_FACTORY_FALLBACK_WARNED", False)
    sentinel_global = MagicMock(name="global_factory")

    import src.infrastructure.adapters.secondary.persistence.database as database_mod

    monkeypatch.setattr(database_mod, "async_session_factory", sentinel_global)

    with caplog.at_level(
        "WARNING", logger="src.infrastructure.adapters.primary.web.websocket.handlers.hitl_handler"
    ):
        first = hitl_handler._resolve_session_factory(None)
        second = hitl_handler._resolve_session_factory(None)

    assert first is sentinel_global
    assert second is sentinel_global
    fallback_records = [r for r in caplog.records if "session_factory not injected" in r.message]
    assert len(fallback_records) == 1


@pytest.mark.unit
def test_resolve_session_factory_passes_through_injected() -> None:
    """P2-18: when factory is provided, no fallback or warning fires."""
    injected = MagicMock(name="injected_factory")
    assert hitl_handler._resolve_session_factory(injected) is injected
