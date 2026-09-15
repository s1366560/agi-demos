"""No-model proof of approved run permission reaching the real tool consumer."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.approved_run_tool_permission_v2 import prepare_approved_run_guard_v2
from src.domain.events.agent_events import AgentObserveEvent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_operation_context_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (  # noqa: F401
    staged,
    verified,
)
from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("profile", ["read_only", "workspace_write", "full_access"])
@pytest.mark.parametrize("permission", ["read", "write", None, "unrecognized"])
async def test_approved_read_only_run_denies_declared_write_at_tool_consumer(  # noqa: PLR0913
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    tmp_path,
    pipeline,
    test_engine,
    staged,  # noqa: F811
    profile,
    permission,
    hook_cancels=False,
    policy_narrows=False,
    revoke_identity=None,
):
    from unittest.mock import AsyncMock

    from src.application.services.agent import runtime_model_route

    monkeypatch.setattr(
        runtime_model_route,
        "load_workspace_policy",
        AsyncMock(
            return_value={
                "permission_mode": {
                    "read_only": "ask",
                    "workspace_write": "automatic",
                    "full_access": "full_access",
                }[profile],
            }
        ),
    )
    body, _execute_model, _ = await _approval_fixture(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        profile,
    )
    body = body.model_copy(update={"permission_profile": profile})
    receipt = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run = await test_db.get(AgentRunAuthorityModel, receipt["run"]["id"])
    assert run.permission_profile == profile
    destination = tmp_path / "write-boundary-proof.txt"

    calls = []

    async def write_fixture(**_kwargs):
        calls.append(True)
        if permission == "read":
            return "Read-only fixture result"
        destination.write_text("Actual write executed under approved read_only canonical run")
        return "written"

    definition = ToolDefinition(
        name="fixture_opaque_operation",
        description="Write test fixture",
        parameters={},
        permission=permission,
        execute=write_fixture,
    )
    manager, _catalog = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="approved-tool-test",
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            session_id=run.conversation_id,
        ),
        services={
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "agent-turn",
                "run_id": run.id,
                "conversation_id": run.conversation_id,
            },
            OPERATION_IDENTITY_SERVICE_V2: {
                "user_id": test_user.id,
                "tenant_id": test_project_db.tenant_id,
                "project_id": test_project_db.id,
            },
        },
    ) as operation:
        await prepare_approved_run_guard_v2(
            operation, run.id, sessions=async_sessionmaker(test_engine, expire_on_commit=False)
        )
        processor = SessionProcessor(
            config=ProcessorConfig(model="never-called", run_id=run.id, approved_run_required=True),
            tools=[definition],
        )
        if hook_cancels or policy_narrows or revoke_identity:

            async def cancel_during_hook(name, payload):
                if name == "before_tool_execution":
                    if revoke_identity:
                        from sqlalchemy import delete

                        from src.infrastructure.adapters.secondary.persistence.models import (
                            UserProject,
                        )

                        if revoke_identity == "user":
                            test_user.is_active = False
                        else:
                            await test_db.execute(
                                delete(UserProject).where(
                                    UserProject.user_id == test_user.id,
                                    UserProject.project_id == test_project_db.id,
                                )
                            )
                        await test_db.commit()
                    if hook_cancels:
                        row = await test_db.get(AgentRunAuthorityModel, run.id)
                        row.status = "cancelled"
                        await test_db.commit()
                    if policy_narrows:
                        monkeypatch.setattr(
                            runtime_model_route,
                            "load_workspace_policy",
                            AsyncMock(return_value={"permission_mode": "ask"}),
                        )
                return payload

            monkeypatch.setattr(processor, "_notify_plugin_hook", cancel_during_hook)
        if pipeline:
            processor._tool_pipeline = ToolPipeline(
                permission_manager=processor.permission_manager,
                doom_detector=processor.doom_loop_detector,
                truncator=OutputTruncator(),
                hooks=ToolHookRegistry(),
            )
        part = ToolPart(call_id="call", tool=definition.name, status=ToolState.RUNNING)
        processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
        processor._pending_tool_calls["call"] = part
        events = [
            event
            async for event in processor._execute_tool(
                run.conversation_id, "call", definition.name, {}
            )
        ]
        observation = next(event for event in events if isinstance(event, AgentObserveEvent))
    allowed = (
        not hook_cancels
        and not revoke_identity
        and (
            permission == "read"
            or (not policy_narrows and profile == "full_access" and permission == "write")
        )
    )
    assert bool(calls) is allowed
    assert destination.exists() is (allowed and permission == "write")
    assert bool(observation.error) is not allowed


@pytest.mark.unit
@pytest.mark.parametrize("parent_status", ["running", "completed", "cancelled"])
async def test_detached_child_restores_durable_ceiling_after_parent_operation_disposal(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    test_engine,
    staged,  # noqa: F811
    parent_status,
):
    from unittest.mock import AsyncMock

    from src.application.services.agent import runtime_model_route

    monkeypatch.setattr(
        runtime_model_route,
        "load_workspace_policy",
        AsyncMock(return_value={"permission_mode": "ask"}),
    )
    from src.application.services.approved_run_tool_permission_v2 import (
        current_approved_run_guard_v2,
        require_approved_run_tool_permission_v2,
    )
    from src.infrastructure.adapters.secondary.persistence.models import AgentPlanRunModel
    from src.infrastructure.agent.subagent.async_run_registry_v2 import (
        AsyncSubAgentRunRegistryV2,
        registry_call_v2,
    )
    from src.infrastructure.agent.subagent.owner_registry_v2 import OWNER_PROTOCOL_V2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    body, _, _ = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "read_only"
    )
    receipt = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run_id = receipt["run"]["id"]
    manager, _catalog = staged
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        session_id=body.conversation_id,
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    registry = AsyncSubAgentRunRegistryV2(sessions)
    async with pin_operation_context_v2(
        manager,
        operation_id="parent-permission",
        scope=scope,
        services={
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "user_id": test_user.id,
            }
        },
    ) as operation:
        await prepare_approved_run_guard_v2(operation, run_id, sessions=sessions)
        await registry_call_v2(
            registry,
            "create_run",
            body.conversation_id,
            "reader",
            "Read fixture",
            run_id="actual-child",
            metadata={
                "execution_protocol": OWNER_PROTOCOL_V2,
                "approved_plan_run_id": "forged",
                "approved_plan_permission_ceiling": "full_access",
            },
        )
        unbound = await registry_call_v2(registry, "get_run", body.conversation_id, "actual-child")
        assert "approved_plan_run_id" not in unbound.metadata
        await registry_call_v2(
            registry,
            "bind_approved_plan_authority",
            body.conversation_id,
            "actual-child",
            approved_run_id=run_id,
            ceiling="read_only",
        )

    canonical = await test_db.get(AgentRunAuthorityModel, run_id)
    source = await test_db.get(AgentPlanRunModel, run_id)
    canonical.status = parent_status
    source.status = "ready_review" if parent_status == "completed" else parent_status
    await test_db.commit()
    async with pin_operation_context_v2(
        manager,
        operation_id="restored-child",
        scope=scope,
        services={
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "detached-subagent",
                "run_id": "actual-child",
                "conversation_id": body.conversation_id,
            },
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "user_id": test_user.id,
            },
        },
    ) as child:
        assert current_approved_run_guard_v2() is None
        async with registry.own_execution(body.conversation_id, "actual-child"):
            if parent_status == "cancelled":
                with pytest.raises(RuntimeV2Error):
                    await require_approved_run_tool_permission_v2("read")
            else:
                await require_approved_run_tool_permission_v2("read")
                assert current_approved_run_guard_v2().operation is child
                with pytest.raises(RuntimeV2Error):
                    await require_approved_run_tool_permission_v2("write")
                with pytest.raises(ValueError):
                    await registry_call_v2(
                        registry,
                        "bind_approved_plan_authority",
                        body.conversation_id,
                        "actual-child",
                        approved_run_id=run_id,
                        ceiling="full_access",
                    )


@pytest.mark.unit
async def test_required_approval_without_run_id_or_operation_fails_closed():
    from src.application.services.approved_run_tool_permission_v2 import (
        require_approved_run_tool_permission_v2,
    )
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    with pytest.raises(RuntimeV2Error):
        await require_approved_run_tool_permission_v2("read", required=True, required_run_id=None)


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    [
        "mark_running",
        "mark_completed",
        "mark_failed",
        "mark_cancelled",
        "mark_timed_out",
        "attach_metadata",
        "create_run",
    ],
)
def test_generic_registry_mutations_cannot_replace_approval_provenance(method):
    from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

    registry = SubAgentRunRegistry()
    registry.create_run("cid", "reader", "task", run_id="child")
    registry.bind_approved_plan_authority(
        "cid", "child", approved_run_id="parent", ceiling="read_only"
    )
    if method in {"mark_completed", "mark_failed"}:
        registry.mark_running("cid", "child")
    forged = {"approved_plan_run_id": "foreign", "approved_plan_permission_ceiling": "full_access"}
    with pytest.raises(ValueError):
        if method == "create_run":
            registry.create_run("cid", "reader", "task", run_id="child", metadata=forged)
        elif method == "mark_failed":
            registry.mark_failed("cid", "child", "error", metadata=forged)
        else:
            getattr(registry, method)("cid", "child", metadata=forged)
    assert (
        registry.get_run("cid", "child").metadata["approved_plan_permission_ceiling"] == "read_only"
    )


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
async def test_cancel_during_before_tool_hook_revokes_previously_approved_write(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    tmp_path,
    pipeline,
    test_engine,
    staged,  # noqa: F811
):
    await test_approved_read_only_run_denies_declared_write_at_tool_consumer(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        tmp_path,
        pipeline,
        test_engine,
        staged,
        "full_access",
        "write",
        hook_cancels=True,
    )


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("permission", ["read", "write"])
async def test_current_core_policy_narrowed_during_hook_keeps_reads_but_rejects_write(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    tmp_path,
    pipeline,
    test_engine,
    staged,  # noqa: F811
    permission,
):
    await test_approved_read_only_run_denies_declared_write_at_tool_consumer(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        tmp_path,
        pipeline,
        test_engine,
        staged,
        "full_access",
        permission,
        policy_narrows=True,
    )


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("revoke_identity", ["user", "project_membership"])
async def test_fresh_identity_revocation_prevents_previously_allowed_read(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    tmp_path,
    pipeline,
    test_engine,
    staged,  # noqa: F811
    revoke_identity,
):
    await test_approved_read_only_run_denies_declared_write_at_tool_consumer(
        monkeypatch,
        test_db,
        test_user,
        test_project_db,
        tmp_path,
        pipeline,
        test_engine,
        staged,
        "read_only",
        "read",
        revoke_identity=revoke_identity,
    )
