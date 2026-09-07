"""Asynchronous dispatch is not legacy completion; actual actor terminal is required."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
    SqlLegacyCronAdmissionRepository,
)
from src.infrastructure.agent.actor import execution, legacy_cron_admission
from src.infrastructure.agent.actor.types import ProjectChatRequest
from src.infrastructure.agent.hitl.state_store import HITLAgentState
from src.infrastructure.scheduler import job_executor
from src.tests.integration.scheduler.test_legacy_cron_admission import admit

pytestmark = pytest.mark.integration


@pytest.fixture
def runtime_io(monkeypatch):
    for name in [
        "set_agent_running",
        "clear_agent_running",
        "_mark_root_run_authority_running",
        "_settle_root_run_authority",
        "_publish_event_to_stream",
        "_persist_events",
        "_run_session_lifecycle",
    ]:
        monkeypatch.setattr(execution, name, AsyncMock())
    monkeypatch.setattr(execution, "_get_last_db_event_time", AsyncMock(return_value=(0, 0)))
    monkeypatch.setattr(execution, "_get_redis_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(execution, "_load_persisted_agent_config", AsyncMock(return_value=None))
    monkeypatch.setattr(execution.agent_metrics, "increment", MagicMock())
    monkeypatch.setattr(execution.agent_metrics, "observe", MagicMock())


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("success", "success"),
        ("failure", "failed"),
        ("error_complete", "failed"),
        ("error_only", "active"),
        ("timeout", "active"),
        ("cancel", "active"),
        ("empty", "active"),
    ],
)
async def test_dispatch_returns_before_true_actor_terminal(
    database, runtime_io, monkeypatch, outcome, expected
):
    _, sessions = database
    monkeypatch.setattr(legacy_cron_admission, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        await session.commit()
    started, finish = asyncio.Event(), asyncio.Event()

    class Agent:
        config = SimpleNamespace(tenant_id="tenant", project_id="project")

        async def execute_chat(self, **kwargs):
            started.set()
            await finish.wait()
            if outcome == "failure":
                raise RuntimeError("closed execution failure")
            if outcome == "timeout":
                raise TimeoutError("execution timeout")
            if outcome == "cancel":
                raise asyncio.CancelledError
            if outcome in {"error_only", "error_complete"}:
                yield {"type": "error", "data": {"message": "closed failure"}}
            if outcome in {"success", "error_complete"}:
                yield {"type": "complete", "data": {"content": "finished"}}

    tasks = []

    async def dispatch(**kwargs):
        assert kwargs["message_id"] == identity.message_id
        assert kwargs["legacy_cron_admission"] == identity.to_wire()
        request = ProjectChatRequest(
            conversation_id=identity.conversation_id,
            message_id=kwargs["message_id"],
            user_message=kwargs["user_message"],
            user_id="user",
            legacy_cron_admission=kwargs["legacy_cron_admission"],
        )
        tasks.append(asyncio.create_task(execution.execute_project_chat(Agent(), request)))
        return "dispatched"

    monkeypatch.setattr(
        job_executor, "_get_bootstrapper", lambda: SimpleNamespace(start_chat_actor=dispatch)
    )
    from src.infrastructure.adapters.secondary.persistence import sql_conversation_repository

    monkeypatch.setattr(
        sql_conversation_repository,
        "SqlConversationRepository",
        lambda _: SimpleNamespace(
            find_by_id=AsyncMock(return_value=SimpleNamespace(id="conversation"))
        ),
    )
    monkeypatch.setattr(
        execution, "_handle_chat_error", AsyncMock(return_value=SimpleNamespace(is_error=True))
    )
    job = SimpleNamespace(id="job", payload=SimpleNamespace(config={"message": "work"}))
    try:
        await job_executor._execute_agent_turn(job, "conversation", MagicMock(), identity)
        await asyncio.wait_for(started.wait(), 5)
        async with sessions() as session:
            assert await SqlLegacyCronAdmissionRepository(session).matches_active(identity)
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions() as session:
            from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
                LegacyCronAdmissionModel,
            )

            row = await session.get(LegacyCronAdmissionModel, identity.admission_id)
            assert row.status == expected
    finally:
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_terminal_storage_failure_keeps_active_blocker(database, monkeypatch):
    _, sessions = database
    monkeypatch.setattr(legacy_cron_admission, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        ticket = await SqlLegacyCronAdmissionRepository(session).claim_execution(identity)
        await session.commit()
    monkeypatch.setattr(
        SqlLegacyCronAdmissionRepository,
        "complete",
        AsyncMock(side_effect=RuntimeError("unavailable")),
    )
    await legacy_cron_admission.complete_legacy_cron_admission(ticket, "success")
    async with sessions() as session:
        assert await SqlLegacyCronAdmissionRepository(session).matches_active(identity)


def test_hitl_state_retains_admission_capability_without_exposing_it_in_repr():
    identity = {"token": "private-capability", "admission_id": "admission"}
    state = HITLAgentState(
        conversation_id="conversation",
        message_id="message",
        tenant_id="tenant",
        project_id="project",
        hitl_request_id="request",
        hitl_type="clarification",
        hitl_request_data={},
        legacy_cron_admission=identity,
    )
    assert HITLAgentState.from_dict(state.to_dict()).legacy_cron_admission == identity
    assert "private-capability" not in repr(state)


async def test_hitl_pause_parks_phase_and_only_one_resume_runs(database, runtime_io, monkeypatch):
    from src.domain.model.agent.hitl.hitl_types import HITLPendingException, HITLType
    from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
        LegacyCronAdmissionModel,
    )
    from src.infrastructure.agent.hitl import coordinator

    _, sessions = database
    monkeypatch.setattr(legacy_cron_admission, "async_session_factory", sessions)
    async with sessions() as session:
        identity = await admit(session)
        await session.commit()
    states = []

    async def save_state(state):
        states.append(state)

    store = SimpleNamespace(save_state=save_state, delete_state_by_request=AsyncMock())
    monkeypatch.setattr(execution, "HITLStateStore", lambda _: store)
    monkeypatch.setattr(execution, "save_hitl_snapshot", AsyncMock())
    monkeypatch.setattr(execution, "delete_hitl_snapshot", AsyncMock())
    monkeypatch.setattr(coordinator, "mark_hitl_request_completed", AsyncMock(return_value=True))
    started, finish = asyncio.Event(), asyncio.Event()

    class Agent:
        config = SimpleNamespace(tenant_id="tenant", project_id="project", agent_mode="default")
        calls = 0

        async def execute_chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise HITLPendingException(
                    request_id="request",
                    hitl_type=HITLType.CLARIFICATION,
                    request_data={"question": "answer"},
                    conversation_id="conversation",
                    message_id=identity.message_id,
                )
            started.set()
            await finish.wait()
            yield {"type": "complete", "data": {"content": "resumed"}}

    agent = Agent()
    request = ProjectChatRequest(
        conversation_id="conversation",
        message_id=identity.message_id,
        user_id="user",
        user_message="work",
        legacy_cron_admission=identity.to_wire(),
    )
    pending = await execution.execute_project_chat(agent, request)
    assert pending.hitl_pending
    assert states[0].legacy_cron_admission == identity.to_wire()
    async with sessions() as session:
        row = await session.get(LegacyCronAdmissionModel, identity.admission_id)
        assert row.status == "active" and row.execution_phase == "waiting"
    monkeypatch.setattr(execution, "_load_hitl_state", AsyncMock(return_value=states[0]))
    first = asyncio.create_task(
        execution.continue_project_chat(
            agent,
            "request",
            {"answer": "yes"},
            tenant_id="tenant",
            project_id="project",
            conversation_id="conversation",
            message_id=identity.message_id,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        with pytest.raises(ValueError, match="execution unavailable"):
            await execution.continue_project_chat(
                agent,
                "request",
                {"answer": "yes"},
                tenant_id="tenant",
                project_id="project",
                conversation_id="conversation",
                message_id=identity.message_id,
            )
        finish.set()
        result = await first
        assert result.content == "resumed" and agent.calls == 2
        async with sessions() as session:
            row = await session.get(LegacyCronAdmissionModel, identity.admission_id)
            assert row.status == "success" and row.execution_phase == "terminal"
    finally:
        finish.set()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("delivery_error", [False, True])
async def test_scheduler_commits_running_admission_before_dispatch(
    database, monkeypatch, delivery_error
):
    from src.domain.model.cron.cron_job import CronJob
    from src.domain.model.cron.value_objects import CronRunStatus
    from src.infrastructure.adapters.secondary.persistence import (
        database as database_module,
        sql_cron_job_repository,
    )

    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    job = CronJob(id="job", tenant_id="tenant", project_id="project", name="fixture")
    monkeypatch.setattr(
        sql_cron_job_repository,
        "SqlCronJobRepository",
        lambda _: SimpleNamespace(find_by_id=AsyncMock(return_value=job), save=AsyncMock()),
    )
    recorded = []

    async def save(run):
        recorded.append(run.status)

    monkeypatch.setattr(
        sql_cron_job_repository, "SqlCronJobRunRepository", lambda _: SimpleNamespace(save=save)
    )
    monkeypatch.setattr(
        job_executor, "_resolve_conversation", AsyncMock(return_value="conversation")
    )
    admitted = []

    async def dispatch(job, conversation_id, session, identity):
        assert recorded == [CronRunStatus.RUNNING]
        async with sessions() as observed:
            assert await SqlLegacyCronAdmissionRepository(observed).matches_active(identity)
        admitted.append(identity)
        if delivery_error:
            raise RuntimeError("delivery outcome unknown")

    monkeypatch.setattr(job_executor, "_execute_payload", dispatch)
    await job_executor.execute_cron_job("job")
    assert len(admitted) == 1
    async with sessions() as session:
        assert await SqlLegacyCronAdmissionRepository(session).matches_active(admitted[0])
