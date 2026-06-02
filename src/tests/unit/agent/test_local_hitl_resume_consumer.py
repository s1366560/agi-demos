"""Unit tests for LocalHITLResumeConsumer response routing."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.persistence import (
    database as database_mod,
    sql_hitl_request_repository as hitl_repo_mod,
)
from src.infrastructure.agent.actor import execution as execution_mod
from src.infrastructure.agent.actor.state import snapshot_repo as snapshot_repo_mod
from src.infrastructure.agent.core import project_react_agent as project_agent_mod
from src.infrastructure.agent.hitl import coordinator as coordinator_mod, utils as hitl_utils
from src.infrastructure.agent.hitl.local_resume_consumer import LocalHITLResumeConsumer


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_agent_does_not_fallback_on_rejected_response(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    resume_mock = AsyncMock()
    reopen_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(consumer, "_resume_via_continue", resume_mock)
    monkeypatch.setattr(consumer, "_reopen_answered_request", reopen_mock)
    monkeypatch.setattr(
        coordinator_mod,
        "resolve_by_request_id",
        lambda *_args, **_kwargs: coordinator_mod.ResolveResult.REJECTED,
    )

    await consumer._resume_agent(
        "tenant-1",
        "project-1",
        "req-1",
        {"values": {"API_KEY": "secret"}},
        "conv-1",
        "msg-1",
    )

    reopen_mock.assert_awaited_once_with("req-1")
    resume_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_agent_falls_back_only_when_coordinator_missing(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    resume_mock = AsyncMock()
    monkeypatch.setattr(consumer, "_resume_via_continue", resume_mock)
    monkeypatch.setattr(
        coordinator_mod,
        "resolve_by_request_id",
        lambda *_args, **_kwargs: coordinator_mod.ResolveResult.NOT_FOUND,
    )

    await consumer._resume_agent(
        "tenant-1",
        "project-1",
        "req-1",
        {"values": {"API_KEY": "secret"}},
        "conv-1",
        "msg-1",
    )

    resume_mock.assert_awaited_once_with(
        "tenant-1",
        "project-1",
        "req-1",
        {"values": {"API_KEY": "secret"}},
        "conv-1",
        "msg-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_message_acks_only_after_successful_resume(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    consumer._ack = AsyncMock()
    monkeypatch.setattr(consumer, "_resume_agent", AsyncMock(return_value=True))
    monkeypatch.setattr(
        hitl_utils,
        "load_persisted_hitl_request",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conv-1",
                message_id="msg-1",
                request_type=SimpleNamespace(value="clarification"),
                metadata={},
            )
        ),
    )

    await consumer._handle_message(
        "hitl:response:tenant-1:project-1",
        "1-0",
        {
            "data": json.dumps(
                {
                    "request_id": "req-1",
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "hitl_type": "clarification",
                    "response_data": {"answer": "ok"},
                }
            )
        },
    )

    await asyncio.gather(*list(consumer._background_tasks))

    consumer._ack.assert_awaited_once_with("hitl:response:tenant-1:project-1", "1-0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_message_prefers_persisted_scope_over_payload(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    resume_and_ack = AsyncMock()
    monkeypatch.setattr(consumer, "_resume_and_ack", resume_and_ack)
    monkeypatch.setattr(
        hitl_utils,
        "load_persisted_hitl_request",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id="tenant-db",
                project_id="project-db",
                conversation_id="conv-db",
                message_id="msg-db",
                request_type=SimpleNamespace(value="clarification"),
                metadata={},
                status="answered",
            )
        ),
    )

    await consumer._handle_message(
        "hitl:response:tenant-stream:project-stream",
        "1-0",
        {
            "data": json.dumps(
                {
                    "request_id": "req-1",
                    "tenant_id": "tenant-payload",
                    "project_id": "project-payload",
                    "conversation_id": "conv-payload",
                    "message_id": "msg-payload",
                    "hitl_type": "clarification",
                    "response_data": {"answer": "ok"},
                }
            )
        },
    )

    await asyncio.gather(*list(consumer._background_tasks))

    resume_and_ack.assert_awaited_once_with(
        "hitl:response:tenant-stream:project-stream",
        "1-0",
        "tenant-db",
        "project-db",
        "req-1",
        {"answer": "ok"},
        "conv-db",
        "msg-db",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_message_keeps_stream_pending_when_resume_fails(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    consumer._ack = AsyncMock()
    monkeypatch.setattr(consumer, "_resume_agent", AsyncMock(return_value=False))
    monkeypatch.setattr(
        hitl_utils,
        "load_persisted_hitl_request",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conv-1",
                message_id="msg-1",
                request_type=SimpleNamespace(value="clarification"),
                metadata={},
            )
        ),
    )

    await consumer._handle_message(
        "hitl:response:tenant-1:project-1",
        "1-0",
        {
            "data": json.dumps(
                {
                    "request_id": "req-1",
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "hitl_type": "clarification",
                    "response_data": {"answer": "ok"},
                }
            )
        },
    )

    await asyncio.gather(*list(consumer._background_tasks))

    consumer._ack.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_message_skips_processing_requests_without_ack(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    consumer._ack = AsyncMock()
    resume_and_ack = AsyncMock()
    monkeypatch.setattr(consumer, "_resume_and_ack", resume_and_ack)
    monkeypatch.setattr(
        hitl_utils,
        "load_persisted_hitl_request",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conv-1",
                message_id="msg-1",
                request_type=SimpleNamespace(value="clarification"),
                metadata={},
                response_metadata={"processing_heartbeat_at": "2000-01-01T00:00:00+00:00"},
                status="processing",
            )
        ),
    )
    monkeypatch.setattr(hitl_utils, "is_processing_lease_stale", lambda *_args, **_kwargs: True)

    await consumer._handle_message(
        "hitl:response:tenant-1:project-1",
        "1-0",
        {"data": json.dumps({"request_id": "req-1", "response_data": {"answer": "ok"}})},
    )

    resume_and_ack.assert_not_awaited()
    consumer._ack.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_message_recovers_stale_processing_requests(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    consumer._ack = AsyncMock()
    resume_and_ack = AsyncMock()
    recover_processing = AsyncMock(return_value=True)
    monkeypatch.setattr(consumer, "_resume_and_ack", resume_and_ack)
    monkeypatch.setattr(consumer, "_recover_stale_processing_request", recover_processing)
    monkeypatch.setattr(
        hitl_utils,
        "load_persisted_hitl_request",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conv-1",
                message_id="msg-1",
                request_type=SimpleNamespace(value="clarification"),
                metadata={},
                response_metadata={"processing_heartbeat_at": "2000-01-01T00:00:00+00:00"},
                status="processing",
            )
        ),
    )
    monkeypatch.setattr(hitl_utils, "is_processing_lease_stale", lambda *_args, **_kwargs: True)

    await consumer._handle_message(
        "hitl:response:tenant-1:project-1",
        "1-0",
        {"data": json.dumps({"request_id": "req-1", "response_data": {"answer": "ok"}})},
        pending_idle_ms=consumer.STALE_PROCESSING_IDLE_MS,
    )

    await asyncio.gather(*list(consumer._background_tasks))

    recover_processing.assert_awaited_once()
    resume_and_ack.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_agent_waits_for_durable_completion(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    wait_completion = AsyncMock()
    monkeypatch.setattr(
        coordinator_mod,
        "resolve_by_request_id",
        lambda *_args, **_kwargs: coordinator_mod.ResolveResult.RESOLVED,
    )
    monkeypatch.setattr(coordinator_mod, "wait_for_request_completion", wait_completion)

    result = await consumer._resume_agent(
        "tenant-1",
        "project-1",
        "req-1",
        {"answer": "ok"},
        "conv-1",
        "msg-1",
    )

    assert result is True
    wait_completion.assert_awaited_once_with("req-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reclaim_pending_messages_claims_idle_entries() -> None:
    redis = MagicMock()
    redis.xpending_range = AsyncMock(
        return_value=[
            {
                "message_id": "1-0",
                "consumer": "dead-consumer",
                "time_since_delivered": 60_000,
            }
        ]
    )
    redis.xclaim = AsyncMock(return_value=[("1-0", {"data": '{"request_id":"req-1"}'})])
    consumer = LocalHITLResumeConsumer(redis)
    consumer._projects.add(("tenant-1", "project-1"))
    consumer._handle_message = AsyncMock()

    await consumer._reclaim_pending_messages(min_idle_ms=1_000)

    redis.xclaim.assert_awaited_once()
    consumer._handle_message.assert_awaited_once_with(
        "hitl:response:tenant-1:project-1",
        "1-0",
        {"data": '{"request_id":"req-1"}'},
        pending_idle_ms=60_000,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_listen_loop_uses_positive_idle_threshold_on_first_reclaim(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    consumer._projects.add(("tenant-1", "project-1"))
    consumer._redis.xreadgroup = AsyncMock(return_value=[])
    reclaim_calls: list[int] = []

    async def _reclaim_pending_messages(*, min_idle_ms: int) -> None:
        reclaim_calls.append(min_idle_ms)
        consumer._running = False

    monkeypatch.setattr(consumer, "_reclaim_pending_messages", _reclaim_pending_messages)
    consumer._running = True

    await consumer._listen_loop()

    assert reclaim_calls == [consumer.RECLAIM_IDLE_MS]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_via_continue_reverts_processing_request_on_error(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    repo = MagicMock()
    repo.claim_for_processing = AsyncMock(return_value=SimpleNamespace(id="req-1"))
    repo.revert_to_answered = AsyncMock(return_value=SimpleNamespace(id="req-1"))

    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = False

    class _FakeAgent:
        def __init__(self) -> None:
            self.stop = AsyncMock()

        async def initialize(self) -> None:
            return None

    fake_agent = _FakeAgent()

    monkeypatch.setattr(database_mod, "async_session_factory", lambda: session_cm)
    monkeypatch.setattr(hitl_repo_mod, "SqlHITLRequestRepository", lambda _session: repo)
    monkeypatch.setattr(
        snapshot_repo_mod,
        "load_hitl_snapshot_agent_mode",
        AsyncMock(return_value="plan"),
    )
    monkeypatch.setattr(consumer, "_has_recoverable_hitl_state", AsyncMock(return_value=True))
    monkeypatch.setattr(project_agent_mod, "ProjectReActAgent", lambda _config: fake_agent)
    monkeypatch.setattr(
        execution_mod,
        "continue_project_chat",
        AsyncMock(return_value=SimpleNamespace(is_error=True, error_message="boom", event_count=0)),
    )

    result = await consumer._resume_via_continue(
        "tenant-1",
        "project-1",
        "req-1",
        {"answer": "ok"},
        "conv-1",
        "msg-1",
    )

    assert result is False
    repo.claim_for_processing.assert_awaited_once_with("req-1", lease_owner=consumer._worker_id)
    repo.revert_to_answered.assert_awaited_once_with("req-1", lease_owner=consumer._worker_id)
    fake_agent.stop.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_via_continue_completes_orphaned_missing_state(monkeypatch) -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())
    repo = MagicMock()
    repo.claim_for_processing = AsyncMock(return_value=SimpleNamespace(id="req-1"))
    repo.revert_to_answered = AsyncMock()

    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = False

    complete_request = AsyncMock(return_value=True)
    agent_factory = MagicMock()

    monkeypatch.setattr(database_mod, "async_session_factory", lambda: session_cm)
    monkeypatch.setattr(hitl_repo_mod, "SqlHITLRequestRepository", lambda _session: repo)
    monkeypatch.setattr(consumer, "_has_recoverable_hitl_state", AsyncMock(return_value=False))
    monkeypatch.setattr(coordinator_mod, "complete_hitl_request", complete_request)
    monkeypatch.setattr(project_agent_mod, "ProjectReActAgent", agent_factory)

    result = await consumer._resume_via_continue(
        "tenant-1",
        "project-1",
        "req-1",
        {"answer": "ok"},
        "conv-1",
        "msg-1",
    )

    assert result is True
    repo.claim_for_processing.assert_awaited_once_with("req-1", lease_owner=consumer._worker_id)
    complete_request.assert_awaited_once_with("req-1", lease_owner=consumer._worker_id)
    repo.revert_to_answered.assert_not_awaited()
    agent_factory.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_cancels_background_tasks() -> None:
    consumer = LocalHITLResumeConsumer(MagicMock())

    async def _never_finishes() -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(_never_finishes())
    consumer._background_tasks.add(task)

    await consumer.stop()

    assert task.cancelled()
    assert not consumer._background_tasks
