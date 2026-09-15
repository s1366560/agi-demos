"""Independent production facades persist before returning and isolate scoped runs."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent.conversation_manager import ConversationManager
from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.fixture
async def registry_setup(test_engine, test_db, test_project_db, test_user):
    conversations = ConversationManager(
        SqlConversationRepository(test_db), SqlAgentExecutionRepository(test_db)
    )
    conversation = await conversations.create_conversation(
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
    )
    await test_db.commit()
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        session_id=conversation.id,
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    return sessions, scope


@pytest.mark.parametrize(
    "terminal_method,status",
    [
        ("mark_completed", SubAgentRunStatus.COMPLETED),
        ("mark_failed", SubAgentRunStatus.FAILED),
        ("mark_cancelled", SubAgentRunStatus.CANCELLED),
    ],
)
async def test_independent_registry_recovers_terminal_and_event_history(
    registry_setup, terminal_method, status
):
    sessions, scope = registry_setup
    first = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(first, "create_run", scope.session_id, "worker", "task")
    await registry_call_v2(first, "mark_running", scope.session_id, run.run_id)
    await registry_call_v2(
        first,
        "attach_metadata",
        scope.session_id,
        run.run_id,
        {
            "announce_events": [
                {"type": "subagent_spawned"},
                {"type": "observe", "call_id": "call-1"},
            ]
        },
    )
    kwargs = (
        {"summary": "done"}
        if terminal_method == "mark_completed"
        else {"error": "failed"}
        if terminal_method == "mark_failed"
        else {"reason": "cancelled"}
    )
    await registry_call_v2(first, terminal_method, scope.session_id, run.run_id, **kwargs)
    recovered = await registry_call_v2(
        AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope),
        "get_run",
        scope.session_id,
        run.run_id,
    )
    assert recovered.status is status
    assert [e["type"] for e in recovered.metadata["announce_events"]] == [
        "subagent_spawned",
        "observe",
    ]


async def test_worker_start_does_not_expire_another_workers_active_run(registry_setup):
    sessions, scope = registry_setup
    worker = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(worker, "create_run", scope.session_id, "worker", "active")
    await registry_call_v2(worker, "mark_running", scope.session_id, run.run_id)
    newcomer = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    recovered = await registry_call_v2(newcomer, "get_run", scope.session_id, run.run_id)
    assert recovered.status is SubAgentRunStatus.RUNNING
    assert "recovered_on_startup" not in recovered.metadata


async def test_wrong_tenant_cannot_read_or_mutate_known_conversation(registry_setup):
    sessions, scope = registry_setup
    from dataclasses import replace

    owner = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(owner, "create_run", scope.session_id, "worker", "private")
    outsider = AsyncSubAgentRunRegistryV2(
        sessions, scope_provider=lambda: replace(scope, tenant_id=str(uuid4()))
    )
    assert await registry_call_v2(outsider, "get_run", scope.session_id, run.run_id) is None
    with pytest.raises(RuntimeV2Error, match="outside scope"):
        await registry_call_v2(outsider, "create_run", scope.session_id, "worker", "intrusion")
    assert len(await registry_call_v2(owner, "list_runs", scope.session_id)) == 1


async def test_production_sync_access_fails_closed(registry_setup):
    sessions, scope = registry_setup
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    with pytest.raises(RuntimeV2Error, match="awaited"):
        registry.create_run(scope.session_id, "worker", "lost write")
