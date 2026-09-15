"""Production tool conversion and conversation-confined task mutation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor.run_context import RunContext, bind_run_context
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.env_var_tools import make_env_var_tools
from src.infrastructure.agent.tools.memory_tools import make_memory_tools
from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool
from src.infrastructure.agent.tools.todo_tools import _todowrite_handle_update, make_todo_tools
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (  # noqa: F401
    staged,
    verified,
)


def _install_read_only_core_policy(monkeypatch, project):
    import json

    class Response:
        status_code = 200

        async def aiter_raw(self):
            yield json.dumps(
                {
                    "tenant_id": project.tenant_id,
                    "project_id": project.id,
                    "workspace_id": "approval-workspace",
                    "revision": 1,
                    "roles": {},
                    "fallbacks": [],
                    "reasoning_effort": "medium",
                    "permission_mode": "ask",
                    "capability_version": "workspace-agent-policy-v1",
                    "updated_at": "2026-09-14T00:00:00Z",
                }
            ).encode()

    client = SimpleNamespace(proxy_request=AsyncMock(return_value=Response()))
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workspace_core_runtime_resolver."
        "workspace_core_runtime_service_v2_from_current_generation",
        lambda: SimpleNamespace(client=client),
    )
    return client


@pytest.mark.unit
@pytest.mark.parametrize("sync", [False, True])
async def test_converted_skill_loader_declares_its_bound_resource_effect(sync):
    service = SimpleNamespace(
        list_available_skills=AsyncMock(return_value=[]),
        load_skill_content=AsyncMock(return_value="# Read instructions"),
        record_skill_usage=AsyncMock(),
    )
    resource_sync = SimpleNamespace(
        sync_for_skill=AsyncMock(return_value=SimpleNamespace(synced=False, resource_paths=[]))
    )
    tool = make_skill_loader_tool(
        skill_service=service,
        tenant_id="tenant",
        project_id="project",
        skill_sync_service=resource_sync if sync else None,
        sandbox_id="sandbox" if sync else "",
    )
    definition = convert_tools({tool.name: tool})[0]
    assert definition.permission == ("skill" if sync else "read")
    result = await definition.execute(name="instructions")
    assert not result.is_error
    assert "Read instructions" in result.output
    assert resource_sync.sync_for_skill.await_count == int(sync)
    service.load_skill_content.assert_awaited_once_with(
        tenant_id="tenant", project_id="project", skill_name="instructions"
    )


@pytest.mark.unit
async def test_converted_todoread_uses_current_conversation(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            pass

    repo = SimpleNamespace(find_by_conversation=AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
        "SqlAgentTaskRepository",
        lambda session: repo,
    )
    definitions = {
        tool.name: tool for tool in convert_tools(make_todo_tools(session_factory=Session))
    }
    assert definitions["todoread"].permission == "read"
    assert definitions["todowrite"].permission == "workspace_task_write"
    with bind_run_context(RunContext(conversation_id="current-conversation")):
        result = await definitions["todoread"].execute()
    assert not result.is_error
    repo.find_by_conversation.assert_awaited_once_with("current-conversation", status=None)


@pytest.mark.unit
async def test_todo_update_cannot_forward_another_conversation_or_model_identity():
    repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(conversation_id="current")),
        update=AsyncMock(return_value=None),
    )
    await _todowrite_handle_update(
        repo,
        SimpleNamespace(commit=AsyncMock()),
        "current",
        "task-owned-by-current",
        [{"status": "pending", "conversation_id": "other", "id": "foreign", "order_index": 99}],
        ToolContext(
            session_id="current",
            conversation_id="current",
            message_id="message",
            call_id="call",
            agent_name="test",
        ),
    )
    repo.update.assert_awaited_once_with("task-owned-by-current", status="pending")


@pytest.mark.unit
@pytest.mark.parametrize("tool_name", ["todoread", "todowrite"])
@pytest.mark.parametrize("mismatched", ["conversation_id", "tenant_id", "project_id"])
async def test_bound_todo_rejects_context_outside_pinned_operation(staged, tool_name, mismatched):  # noqa: F811
    from unittest.mock import Mock

    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
    from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    manager, _catalog = staged
    session_factory = Mock(side_effect=AssertionError("must reject before opening storage"))
    tool = make_todo_tools(session_factory=session_factory)[tool_name]
    fields = {
        "session_id": "session",
        "conversation_id": "session",
        "tenant_id": "tenant",
        "project_id": "project",
        "message_id": "message",
        "call_id": "call",
        "agent_name": "agent",
    }
    fields[mismatched] = "other"
    async with pin_operation_context_v2(
        manager,
        operation_id="task-permission-scope",
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION, tenant_id="tenant", project_id="project", session_id="session"
        ),
    ):
        with pytest.raises(RuntimeV2Error, match="Task tool context"):
            await tool.execute(
                ToolContext(**fields),
                **({"action": "replace", "todos": []} if tool_name == "todowrite" else {}),
            )
    session_factory.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool_name",
    [
        "todoread",
        "skill_loader",
        "sessions_list",
        "memory_search",
        "check_env_vars",
        "get_env_var",
        "request_env_var",
        "todo_progress",
        "todo_scope_change",
    ],
)
@pytest.mark.parametrize("pipeline", [False, True])
async def test_approved_read_only_run_executes_real_converted_read_tools(  # noqa: PLR0915
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    test_engine,
    staged,  # noqa: F811
    tool_name,
    pipeline,
):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.application.services.approved_run_tool_permission_v2 import (
        prepare_approved_run_guard_v2,
    )
    from src.domain.events.agent_events import AgentObserveEvent
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
    from src.infrastructure.adapters.primary.web.routers.agent import plans
    from src.infrastructure.adapters.secondary.persistence.models import AgentTaskModel
    from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
    from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
    from src.infrastructure.agent.tools.hooks import ToolHookRegistry
    from src.infrastructure.agent.tools.pipeline import ToolPipeline
    from src.infrastructure.agent.tools.truncation import OutputTruncator
    from src.infrastructure.plugins.v2.boundary import (
        OPERATION_IDENTITY_SERVICE_V2,
        OPERATION_METADATA_SERVICE_V2,
        pin_operation_context_v2,
    )
    from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture

    body, _model, _ = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "read_only"
    )
    core_client = _install_read_only_core_policy(monkeypatch, test_project_db)
    test_db.add(
        AgentTaskModel(
            id="current-task",
            conversation_id=body.conversation_id,
            content="Approved task",
            title="Approved task",
            status="pending",
        )
    )
    await test_db.commit()
    receipt = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run_id = receipt["run"]["id"]
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    service = SimpleNamespace(
        list_available_skills=AsyncMock(return_value=[]),
        load_skill_content=AsyncMock(return_value="# Instructions under read-only approval"),
        record_skill_usage=AsyncMock(),
    )
    raw = (
        make_todo_tools(session_factory=sessions)["todoread"]
        if tool_name == "todoread"
        else make_skill_loader_tool(
            skill_service=service,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
        )
    )
    definition = convert_tools({tool_name: raw})[0]
    arguments = {"name": "instructions"} if tool_name == "skill_loader" else {}
    env_repository = SimpleNamespace(get_for_tool=AsyncMock(return_value=[]), get=AsyncMock())
    env_encryption = SimpleNamespace(decrypt=AsyncMock())
    if tool_name in {"check_env_vars", "get_env_var", "request_env_var"}:
        env_definitions = {
            item.name: item
            for item in convert_tools(
                make_env_var_tools(repository=env_repository, encryption_service=env_encryption)
            )
        }
        assert {name: item.permission for name, item in env_definitions.items()} == {
            "check_env_vars": "read",
            "get_env_var": "system_api",
            "request_env_var": "system_api",
        }
        definition = env_definitions[tool_name]
        arguments = {"tool_name": "qa_tool"}
        arguments.update(
            {
                "check_env_vars": {"required_vars": ["QA_CONFIG"]},
                "get_env_var": {"variable_name": "QA_CONFIG"},
                "request_env_var": {"fields": [{"variable_name": "QA_CONFIG"}]},
            }[tool_name]
        )
    memory_search = SimpleNamespace(search=AsyncMock(return_value=[]))
    if tool_name == "memory_search":
        memory_definitions = {
            item.name: item
            for item in convert_tools(
                make_memory_tools(
                    tenant_id=test_project_db.tenant_id,
                    project_id=test_project_db.id,
                    graph_service=None,
                    chunk_search=memory_search,
                    session_factory=sessions,
                )
            )
        }
        assert {name: item.permission for name, item in memory_definitions.items()} == {
            "memory_search": "read",
            "memory_get": "read",
            "memory_create": "write",
            "memory_update": "write",
            "memory_delete": "write",
        }
        definition = memory_definitions["memory_search"]
        arguments = {"query": "approved scope"}
    if tool_name in {"todo_progress", "todo_scope_change"}:
        definition = next(
            item
            for item in convert_tools(make_todo_tools(session_factory=sessions))
            if item.name == "todowrite"
        )
        patch = {"status": "completed", "result_summary": "Read-only verification finished"}
        if tool_name == "todo_scope_change":
            patch["content"] = "Replace the approved scope"
        arguments = {"action": "update", "todo_id": "current-task", "todos": [patch]}
    if tool_name == "sessions_list":
        from src.tests.unit.infrastructure.agent.tools.test_subagent_tool_runtime_isolation import (
            _build_tools,
            _spawn_callback,
        )

        definition = next(
            item
            for item in _build_tools(
                conversation_id=body.conversation_id, delegate_callback=_spawn_callback
            )
            if item.name == "sessions_list"
        )
    processor = SessionProcessor(
        config=ProcessorConfig(model="never-called", run_id=run_id, approved_run_required=True),
        tools=[definition],
    )
    processor._langfuse_context = {
        "conversation_id": body.conversation_id,
        "tenant_id": test_project_db.tenant_id,
        "project_id": test_project_db.id,
        "user_id": test_user.id,
    }
    if pipeline:
        processor._tool_pipeline = ToolPipeline(
            permission_manager=processor.permission_manager,
            doom_detector=processor.doom_loop_detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
    part = ToolPart(call_id="read-call", tool=definition.name, status=ToolState.RUNNING)
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
    processor._pending_tool_calls[part.call_id] = part
    manager, _ = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="production-read-tools",
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            session_id=body.conversation_id,
        ),
        services={
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "agent-turn",
                "run_id": run_id,
                "conversation_id": body.conversation_id,
            },
            OPERATION_IDENTITY_SERVICE_V2: {
                "user_id": test_user.id,
                "tenant_id": test_project_db.tenant_id,
                "project_id": test_project_db.id,
            },
        },
    ) as operation:
        await prepare_approved_run_guard_v2(operation, run_id, sessions=sessions)
        with bind_run_context(RunContext(conversation_id=body.conversation_id)):
            events = [
                event
                async for event in processor._execute_tool(
                    body.conversation_id,
                    part.call_id,
                    definition.name,
                    arguments,
                )
            ]
    observations = [event for event in events if isinstance(event, AgentObserveEvent)]
    denied = tool_name in {"todo_scope_change", "get_env_var", "request_env_var"}
    assert observations and all(bool(event.error) is denied for event in observations)
    assert part.status == (ToolState.ERROR if denied else ToolState.COMPLETED)
    async with sessions() as db:
        task = await db.get(AgentTaskModel, "current-task")
        assert task.content == "Approved task"
        assert task.status == ("completed" if tool_name == "todo_progress" else "pending")
    if tool_name == "skill_loader":
        service.load_skill_content.assert_awaited_once()
    if tool_name == "memory_search":
        memory_search.search.assert_awaited_once()
        assert memory_search.search.await_args.kwargs["project_id"] == test_project_db.id
    if tool_name == "check_env_vars":
        env_repository.get_for_tool.assert_awaited_once()
        assert (
            env_repository.get_for_tool.await_args.kwargs["tenant_id"] == test_project_db.tenant_id
        )
        assert env_repository.get_for_tool.await_args.kwargs["project_id"] == test_project_db.id
    env_repository.get.assert_not_called()
    env_encryption.decrypt.assert_not_called()
    assert core_client.proxy_request.await_count > 0
