"""Diagnostic: real approved authority cancelled between transport attempts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent import runtime_model_route
from src.application.services.approved_run_tool_permission_v2 import prepare_approved_run_guard_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.sandbox_port import SandboxStatus
from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.sandbox_tool_wrapper import create_sandbox_mcp_tool
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_operation_context_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import staged, verified
from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture


@pytest.mark.unit
async def test_transport_retry_does_not_dispatch_after_real_run_cancel(
    monkeypatch, test_db, test_user, test_project_db, test_engine, staged
):
    body, _, environment = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "workspace_write"
    )
    environment.return_value = {
        "id": "retry-sandbox",
        "kind": "cloud",
        "workspace_path": "/workspace",
    }
    monkeypatch.setattr(
        runtime_model_route,
        "load_workspace_policy",
        AsyncMock(return_value={"permission_mode": "automatic"}),
    )
    body = body.model_copy(update={"permission_profile": "workspace_write"})
    receipt = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run_id = receipt["run"]["id"]
    calls = []
    instance = SimpleNamespace(
        id="retry-sandbox",
        status=SandboxStatus.RUNNING,
        labels={
            "memstack.tenant_id": test_project_db.tenant_id,
            "memstack.project_id": test_project_db.id,
        },
    )

    async def call_tool(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            row = await test_db.get(AgentRunAuthorityModel, run_id)
            row.status = "cancelled"
            await test_db.commit()
            raise ConnectionError("Connection reset by peer")
        return {"content": [{"type": "text", "text": "unexpected retry dispatch"}]}

    port = SimpleNamespace(get_sandbox=AsyncMock(return_value=instance), call_tool=call_tool)
    schema = {
        "name": "write",
        "input_schema": {},
        "_meta": {
            "memstack/workspace-write": {
                "contract": "directory-fd-write-v1",
                "workspace_root": "/workspace",
            }
        },
    }
    tool = create_sandbox_mcp_tool("retry-sandbox", "write", schema, port)
    manager, _ = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="retry-proof",
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            session_id=body.conversation_id,
        ),
        services={
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": test_project_db.tenant_id,
                "project_id": test_project_db.id,
                "user_id": test_user.id,
            },
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "agent-turn",
                "run_id": run_id,
                "conversation_id": body.conversation_id,
            },
        },
    ) as operation:
        await prepare_approved_run_guard_v2(
            operation, run_id, sessions=async_sessionmaker(test_engine, expire_on_commit=False)
        )
        result = await tool.execute(
            ToolContext(
                session_id=body.conversation_id,
                conversation_id=body.conversation_id,
                message_id="m",
                call_id="c",
                agent_name="qa",
            ),
            file_path="marker.txt",
            content="qa",
        )
    assert len(calls) == 1, (
        f"cancelled authority dispatched {len(calls)} transport attempts; result.is_error={result.is_error}"
    )
