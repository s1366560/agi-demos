"""Unit tests for WebSocket HITL handler safeguards."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.hitl_authority import classify_hitl_authority_conflict
from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.websocket.handlers import hitl_handler
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.agent.hitl import utils as hitl_utils
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)


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
async def test_publish_hitl_response_uses_v2_operation_redis(monkeypatch) -> None:
    redis_client = SimpleNamespace(xadd=AsyncMock(return_value="1-0"))
    pin_calls: list[dict[str, object]] = []
    reservation = object()
    acquire = AsyncMock(return_value=reservation)
    monkeypatch.setattr(hitl_handler, "acquire_existing_scoped_session_v2", acquire)

    @asynccontextmanager
    async def pin_operation(received: object, **kwargs: object):
        assert received is reservation
        pin_calls.append(dict(kwargs))
        yield object()

    async def reject_process_global_redis() -> object:
        raise AssertionError("process-global Redis authority must not be used")

    from src.configuration import config as config_module
    from src.infrastructure.agent.state import agent_worker_state

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(hitl_realtime_enabled=True),
    )
    monkeypatch.setattr(agent_worker_state, "get_redis_client", reject_process_global_redis)
    monkeypatch.setattr(
        hitl_handler,
        "pin_scoped_agent_turn_operation_v2",
        pin_operation,
        raising=False,
    )
    monkeypatch.setattr(
        hitl_handler,
        "current_agent_worker_redis_client_v2",
        lambda: redis_client,
        raising=False,
    )

    context = _make_context()
    published = await hitl_handler._publish_hitl_response_to_redis(
        context=context,
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        message_id="message-1",
        request_id="request-1",
        hitl_type="decision",
        response_data={"decision": "approve"},
        user_id="user-1",
        agent_mode="default",
    )

    acquire.assert_awaited_once_with(
        context,
        conversation_id="conversation-1",
        project_id="project-1",
        hitl_request_id="request-1",
    )
    assert published is True
    assert pin_calls == [
        {
            "operation_id": "agent-hitl-response-publish:request-1",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "session_id": "conversation-1",
            "services": {
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "user_id": "user-1",
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-hitl-response-publish",
                    "channel": "websocket",
                    "request_id": "request-1",
                    "conversation_id": "conversation-1",
                    "message_id": "message-1",
                    "hitl_type": "decision",
                },
            },
        }
    ]
    redis_client.xadd.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_recovery_forks_v2_stream_from_scoped_admission(monkeypatch) -> None:
    context = _make_context()
    manager = MagicMock()
    manager.bridge_tasks = {"session-1": {}}
    manager.subscribe = AsyncMock()
    context._connection_manager = manager
    hitl_request = _make_hitl_request(request_type=HITLRequestType.DECISION)
    repository = SimpleNamespace(get_by_id=AsyncMock(return_value=hitl_request))
    pin_calls: list[dict[str, object]] = []
    reservation = object()
    acquire = AsyncMock(return_value=reservation)
    monkeypatch.setattr(hitl_handler, "acquire_existing_scoped_session_v2", acquire)

    @asynccontextmanager
    async def pin_operation(received: object, **kwargs: object):
        assert received is reservation
        pin_calls.append(dict(kwargs))
        yield object()

    from src.infrastructure.adapters.primary.web.websocket.handlers import subscription_handler
    from src.infrastructure.adapters.secondary.persistence import (
        sql_hitl_request_repository as repository_module,
    )

    start_bridge = AsyncMock(return_value=True)
    monkeypatch.setattr(
        repository_module,
        "SqlHITLRequestRepository",
        lambda _db: repository,
    )
    monkeypatch.setattr(hitl_handler, "pin_scoped_agent_turn_operation_v2", pin_operation)
    monkeypatch.setattr(
        subscription_handler,
        "_start_recovery_bridge_task_v2",
        start_bridge,
    )

    await hitl_handler._start_hitl_stream_bridge(context, "req-1")

    acquire.assert_awaited_once_with(
        context, conversation_id="conv-1", project_id="project-1", hitl_request_id="req-1"
    )
    manager.subscribe.assert_awaited_once_with("session-1", "conv-1")
    assert pin_calls == [
        {
            "operation_id": "agent-hitl-recovery-admission:req-1",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "session_id": "conv-1",
            "services": {
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "user_id": "user-1",
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-hitl-recovery-admission",
                    "channel": "websocket",
                    "request_id": "req-1",
                    "conversation_id": "conv-1",
                    "message_id": "msg-1",
                },
            },
        }
    ]
    start_bridge.assert_awaited_once_with(
        context=context,
        conversation_id="conv-1",
        message_id=None,
        replay_from_db=True,
        cursor_time_us=None,
        cursor_counter=None,
        operation_kind="agent-hitl-recovery-stream",
        hitl_request_id="req-1",
    )


@pytest.mark.unit
def test_hitl_recovery_has_no_static_llm_or_agent_service_factory() -> None:
    source = Path(hitl_handler.__file__).read_text(encoding="utf-8")

    assert "create_llm_client" not in source
    assert "get_scoped_container().agent_service" not in source
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source


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
    assert payload["data"]["message"] == "HITL request has expired"
    assert payload["data"]["code"] == "hitl_request_expired"
    assert payload["data"]["reason_code"] == "hitl_request_expired"
    assert payload["data"]["authority_revision"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_hitl_response_returns_structured_authority_when_claim_is_lost(
    monkeypatch,
) -> None:
    context = _make_context()
    pending = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    answered = _make_hitl_request(request_type=HITLRequestType.CLARIFICATION)
    answered.status = HITLRequestStatus.ANSWERED
    answered.answered_at = datetime.now(UTC)
    conflict = classify_hitl_authority_conflict(answered)

    monkeypatch.setattr(
        hitl_handler,
        "_load_hitl_request",
        AsyncMock(return_value=pending),
    )
    monkeypatch.setattr(hitl_handler, "_user_has_hitl_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        hitl_handler,
        "_persist_hitl_response",
        AsyncMock(side_effect=conflict),
    )
    publish_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(hitl_handler, "_publish_hitl_response_to_redis", publish_mock)

    await hitl_handler._handle_hitl_response(
        context=context,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "second answer"},
        ack_type="clarification_response_ack",
    )

    payload = context.websocket.send_json.await_args.args[0]
    assert payload["type"] == "error"
    assert payload["data"]["message"] == "HITL request is no longer pending"
    assert payload["data"]["code"] == "hitl_already_answered"
    assert payload["data"]["reason_code"] == "hitl_already_answered"
    assert payload["data"]["authority_status"] == "answered"
    assert payload["data"]["answered_at"] == answered.answered_at.isoformat()
    publish_mock.assert_not_awaited()


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
