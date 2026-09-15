"""A denied peer execution never reaches the message bus or executor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.application.services.peer_chat_permission_v2 import preflight_session_turn_v2
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.routers.agent.test_chat_run_permission_guard_v2 import (  # noqa: F401
    chat_guard_case,
    staged,
    verified,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario", ["active", "owner", "start_failure", "bus_failure", "success", "response"]
)
async def test_formal_peer_preflight_precedes_delivery(
    chat_guard_case,  # noqa: F811
    test_db,
    monkeypatch,
    scenario,
):
    async with chat_guard_case() as (source, _policy):
        parent = await test_db.get(Conversation, source.conversation_id)
        peer = Conversation(
            id="delivery-peer",
            tenant_id=source.tenant_id,
            project_id=source.project_id,
            user_id=parent.user_id,
            parent_conversation_id=parent.id,
            workspace_id="peer-workspace",
            title="Delivery peer",
        )
        if scenario == "owner":
            other = User(
                id="other-peer-user",
                email="other-peer@example.test",
                hashed_password="test-only",
                is_active=True,
            )
            test_db.add(other)
            await test_db.flush()
            peer.user_id = other.id
        test_db.add(peer)
        await test_db.commit()
        if scenario == "active":
            await ensure_chat_run_authority(
                test_db,
                conversation=peer,
                run_id="already-active-peer",
                request_message="Active peer",
                client_message_id="active-peer",
                app_model_context=None,
            )
        monkeypatch.setattr(
            AgentRuntimeBootstrapper,
            "load_spawned_agent_conversation",
            AsyncMock(return_value=peer),
        )
        bus = SimpleNamespace(send_message=AsyncMock(return_value="bus-message"))
        executor = AsyncMock()
        if scenario == "start_failure":
            executor.side_effect = RuntimeError("Executor rejected admission")
        if scenario == "bus_failure":
            bus.send_message.side_effect = RuntimeError("Message transport unavailable")
        orchestrator = AgentOrchestrator(
            agent_registry=MagicMock(),
            session_registry=MagicMock(),
            spawn_manager=SimpleNamespace(
                get_record=AsyncMock(
                    return_value=SimpleNamespace(
                        mode=SpawnMode.SESSION, project_id=source.project_id
                    )
                )
            ),
            message_bus=bus,
            session_turn_executor=executor,
            session_turn_preflight=preflight_session_turn_v2,
        )
        orchestrator._resolve_message_sender = AsyncMock(
            return_value=SimpleNamespace(id="sender", name="Sender")
        )
        orchestrator._resolve_message_target = AsyncMock(
            return_value=SimpleNamespace(id="peer", name="Peer")
        )
        orchestrator._resolve_message_session_id = AsyncMock(return_value=peer.id)
        orchestrator._validate_message_sender_session = AsyncMock()

        async def send():
            return await orchestrator.send_message(
                "sender",
                "peer",
                "Peer request",
                project_id=source.project_id,
                tenant_id=source.tenant_id,
                sender_session_id=source.conversation_id,
                session_id=peer.id,
                message_type=AgentMessageType.RESPONSE
                if scenario == "response"
                else AgentMessageType.REQUEST,
            )

        if scenario in {"active", "owner"}:
            with pytest.raises(RuntimeV2Error):
                await send()
            bus.send_message.assert_not_awaited()
            executor.assert_not_awaited()
        elif scenario in {"start_failure", "bus_failure"}:
            with pytest.raises(RuntimeError):
                await send()
            run = await test_db.scalar(
                select(AgentRunAuthorityModel).where(
                    AgentRunAuthorityModel.conversation_id == peer.id
                )
            )
            assert run.status == "failed"
            assert run.error == "Peer session delivery or execution admission failed"
            assert executor.await_count == (1 if scenario == "start_failure" else 0)
        else:
            result = await send()
            assert result.message_id == "bus-message"
            assert bus.send_message.await_count == 1
            assert executor.await_count == (0 if scenario == "response" else 1)
            if scenario == "success":
                admission = executor.await_args.args[0].admission
                run = await test_db.get(AgentRunAuthorityModel, admission.run_id)
                assert run.status == "queued"
                assert run.authorization_snapshot["sender_authority"]["run_id"] == source.id
