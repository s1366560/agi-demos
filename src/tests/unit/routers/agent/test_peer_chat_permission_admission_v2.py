"""Peer session launches must create canonical authority without invoking a model."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    SessionTurnExecutionRequest,
    SpawnExecutionRequest,
)
from src.tests.unit.routers.agent.test_chat_run_permission_guard_v2 import (  # noqa: F401
    chat_guard_case,
    staged,
    verified,
)


@pytest.mark.unit
@pytest.mark.parametrize("spawn", [False, True])
@pytest.mark.parametrize("runtime", ["bootstrap", "ray"])
async def test_peer_launcher_creates_canonical_run_with_trusted_sender(
    chat_guard_case,  # noqa: F811
    test_db,
    monkeypatch,
    spawn,
    runtime,
):
    async with chat_guard_case() as (sender, _policy):
        peer = Conversation(
            id="peer-session",
            tenant_id=sender.tenant_id,
            project_id=sender.project_id,
            user_id="unused",
            parent_conversation_id=sender.conversation_id,
            title="Peer canonical admission",
            workspace_id="chat-guard-workspace",
        )
        parent = await test_db.get(Conversation, sender.conversation_id)
        peer.user_id = parent.user_id
        test_db.add(peer)
        await test_db.commit()
        bootstrapper = AgentRuntimeBootstrapper()
        monkeypatch.setattr(
            AgentRuntimeBootstrapper,
            "ensure_spawned_agent_conversation",
            AsyncMock(return_value=peer),
        )
        monkeypatch.setattr(
            AgentRuntimeBootstrapper,
            "load_spawned_agent_conversation",
            AsyncMock(return_value=peer),
        )
        start = AsyncMock()
        monkeypatch.setattr(bootstrapper, "start_chat_actor", start)
        launcher = (
            bootstrapper.launch_spawned_agent_session
            if spawn
            else bootstrapper.launch_agent_session_turn
        )
        actor = None
        if runtime == "ray":
            from src.infrastructure.plugins.v2.boundary import (
                OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
                current_operation_context_v2,
            )
            from src.tests.unit.infrastructure.agent.actor.test_project_agent_actor import (
                _actor_instance,
            )

            operation = current_operation_context_v2()
            operation.provide(
                OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
                {"descriptor": operation.descriptor.to_payload()},
            )
            actor = _actor_instance()
            bind = AsyncMock(return_value=object())
            monkeypatch.setattr(
                "src.infrastructure.plugins.v2.agent_worker_runtime.bind_current_agent_orchestrator_v2",
                bind,
            )
            monkeypatch.setattr(
                AgentRuntimeBootstrapper,
                "_load_tenant_agent_config",
                AsyncMock(return_value=SimpleNamespace(to_dict=dict)),
            )
            peer.is_in_plan_mode = False
            actor.chat = start
            await actor._ensure_agent_orchestrator_v2()
            launcher = bind.await_args.kwargs[
                "spawn_executor" if spawn else "session_turn_executor"
            ]
        metadata = {"permission_profile": "full_access", "sender_authority": {"run_id": "forged"}}
        if spawn:
            request = SpawnExecutionRequest(
                parent_agent_id="parent-agent",
                child_agent_id="child-agent",
                child_agent_name="Child",
                child_session_id=peer.id,
                parent_session_id=sender.conversation_id,
                project_id=sender.project_id,
                tenant_id=sender.tenant_id,
                user_id=parent.user_id,
                message="Peer turn",
                metadata=metadata,
            )
        else:
            request = SessionTurnExecutionRequest(
                child_agent_id="child-agent",
                child_session_id=peer.id,
                project_id=peer.project_id,
                tenant_id=peer.tenant_id,
                message="Peer turn",
                source_message_id="peer-source",
                sender_agent_id="parent-agent",
                metadata=metadata,
            )
        from dataclasses import replace

        from src.application.services.peer_chat_permission_v2 import prepare_peer_execution_v2

        admission = await prepare_peer_execution_v2(request, spawn=spawn)
        admitted = replace(request, admission=admission)
        await launcher(admitted)
        await launcher(admitted)
        await launcher(request)
        assert start.await_count == 1
        payload = (
            start.await_args.kwargs if runtime == "bootstrap" else vars(start.await_args.args[0])
        )
        run_id = payload.get("canonical_run_id")
        assert run_id, "Peer launches bypass canonical run admission"
        assert payload["message_id"] == run_id
        run = await test_db.get(AgentRunAuthorityModel, run_id)
        assert run is not None and run.conversation_id == peer.id
        assert run.authorization_snapshot["sender_authority"]["run_id"] == sender.id
        assert run.authorization_snapshot["effective_permission_mode"] == "ask"
        if actor is not None:
            await actor._plugin_admission_v2.close()


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario",
    [
        "readonly",
        "full",
        "completed",
        "lower_before",
        "lower_after",
        "cancelled",
        "inactive",
        "transitive",
    ],
)
async def test_peer_execution_preserves_sender_ceiling_and_lifecycle(  # noqa: PLR0915
    test_db,
    test_engine,
    test_user,
    test_project_db,
    monkeypatch,
    staged,  # noqa: F811
    scenario,
):
    from src.application.services.approved_run_tool_permission_v2 import (
        prepare_approved_run_guard_v2,
    )
    from src.application.services.chat_run_tool_permission_v2 import (
        approved_chat_tool_call_v2,
        decision_for_current_chat_tool_v2,
        prepare_chat_run_guard_v2,
    )
    from src.application.services.peer_chat_permission_v2 import prepare_peer_execution_v2
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
    from src.infrastructure.adapters.primary.web.routers.agent import plans
    from src.infrastructure.adapters.secondary.persistence.models import AgentPlanRunModel, User
    from src.infrastructure.plugins.v2.boundary import (
        OPERATION_IDENTITY_SERVICE_V2,
        OPERATION_METADATA_SERVICE_V2,
        pin_operation_context_v2,
    )
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
    from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture

    body, _execute, _environment = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "full_access"
    )
    if scenario not in {"readonly", "transitive"}:
        body = body.model_copy(update={"permission_profile": "full_access"})
    result = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    source = await test_db.get(AgentRunAuthorityModel, result["run"]["id"])
    policy_state = {"source": "ask" if scenario == "lower_before" else "full_access"}

    async def policy(conversation):
        return {
            "revision": 9,
            "permission_mode": policy_state["source"]
            if conversation.id == source.conversation_id
            else "full_access",
        }

    monkeypatch.setattr(
        "src.application.services.agent.runtime_model_route.load_workspace_policy", policy
    )
    monkeypatch.setattr(
        "src.application.services.chat_permission_admission_v2.load_workspace_policy", policy
    )
    peer = Conversation(
        id="peer-boundary",
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        user_id=test_user.id,
        parent_conversation_id=source.conversation_id,
        workspace_id="peer-full-workspace",
        title="Peer boundary",
    )
    test_db.add(peer)
    await test_db.commit()
    monkeypatch.setattr(
        AgentRuntimeBootstrapper, "load_spawned_agent_conversation", AsyncMock(return_value=peer)
    )
    manager, _catalog = staged
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    def operation_kwargs(cid, run_id):
        return {
            "operation_id": f"peer-boundary:{cid}",
            "scope": ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=source.tenant_id,
                project_id=source.project_id,
                session_id=cid,
            ),
            "services": {
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": source.tenant_id,
                    "project_id": source.project_id,
                    "user_id": test_user.id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-turn",
                    "run_id": run_id,
                    "conversation_id": cid,
                },
            },
        }

    async with pin_operation_context_v2(
        manager, **operation_kwargs(source.conversation_id, source.id)
    ) as operation:
        await prepare_approved_run_guard_v2(operation, source.id, sessions=sessions)
        admission = await prepare_peer_execution_v2(
            SessionTurnExecutionRequest(
                child_agent_id="peer",
                child_session_id=peer.id,
                project_id=source.project_id,
                tenant_id=source.tenant_id,
                source_message_id="peer-boundary-turn",
                message="A peer request",
            ),
            spawn=False,
        )
    peer_run = await test_db.get(AgentRunAuthorityModel, admission.run_id)
    if scenario in {"readonly", "lower_before", "transitive"}:
        assert (
            peer_run.authorization_snapshot["sender_authority"]["permission_profile"] == "read_only"
        )
        assert peer_run.authorization_snapshot["effective_permission_mode"] == "ask"
    if scenario == "lower_after":
        policy_state["source"] = "ask"
    if scenario in {"completed", "cancelled"}:
        source.status = scenario
        plan_run = await test_db.get(AgentPlanRunModel, source.plan_run_id)
        plan_run.status = scenario
        await test_db.commit()
    if scenario == "inactive":
        user = await test_db.get(User, test_user.id)
        user.is_active = False
        await test_db.commit()

    async with pin_operation_context_v2(
        manager, **operation_kwargs(peer.id, peer_run.id)
    ) as operation:
        if scenario in {"inactive", "cancelled"}:
            with pytest.raises(RuntimeV2Error):
                await prepare_chat_run_guard_v2(operation, peer_run.id, sessions=sessions)
                await decision_for_current_chat_tool_v2("read", "opaque", {}, required=True)
        else:
            await prepare_chat_run_guard_v2(operation, peer_run.id, sessions=sessions)
            assert (
                await decision_for_current_chat_tool_v2("read", "opaque", {}, required=True)
                == "allow"
            )
            with approved_chat_tool_call_v2("opaque", {}):
                if scenario in {"full", "completed"}:
                    assert (
                        await decision_for_current_chat_tool_v2(
                            "write", "opaque", {}, required=True
                        )
                        == "allow"
                    )
                else:
                    with pytest.raises(RuntimeV2Error):
                        await decision_for_current_chat_tool_v2(
                            "write", "opaque", {}, required=True
                        )
            if scenario == "transitive":
                third = Conversation(
                    id="third-peer",
                    tenant_id=source.tenant_id,
                    project_id=source.project_id,
                    user_id=test_user.id,
                    parent_conversation_id=peer.id,
                    workspace_id="third-full-workspace",
                    title="Third peer",
                )
                test_db.add(third)
                await test_db.commit()
                monkeypatch.setattr(
                    AgentRuntimeBootstrapper,
                    "load_spawned_agent_conversation",
                    AsyncMock(return_value=third),
                )
                third_admission = await prepare_peer_execution_v2(
                    SessionTurnExecutionRequest(
                        child_agent_id="third",
                        child_session_id=third.id,
                        project_id=source.project_id,
                        tenant_id=source.tenant_id,
                        source_message_id="third-turn",
                        message="Third request",
                    ),
                    spawn=False,
                )
    if scenario == "transitive":
        source.status = "completed"
        plan_run = await test_db.get(AgentPlanRunModel, source.plan_run_id)
        plan_run.status = "completed"
        await test_db.commit()
        async with pin_operation_context_v2(
            manager, **operation_kwargs(third.id, third_admission.run_id)
        ) as operation:
            await prepare_chat_run_guard_v2(operation, third_admission.run_id, sessions=sessions)
            assert (
                await decision_for_current_chat_tool_v2("read", "opaque", {}, required=True)
                == "allow"
            )
            with approved_chat_tool_call_v2("opaque", {}), pytest.raises(RuntimeV2Error):
                await decision_for_current_chat_tool_v2("write", "opaque", {}, required=True)
