"""Real factory metadata through the SQL-backed approved-run guard, without I/O."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent import runtime_model_route
from src.application.services.approved_run_tool_permission_v2 import (
    prepare_approved_run_guard_v2,
    require_approved_run_tool_permission_v2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.tools.sandbox_tool_wrapper import create_sandbox_mcp_tool
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import ToolSetCatalogV2, ToolSetV2
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (  # noqa: F401
    staged,
    verified,
)
from src.tests.unit.routers.agent.test_plan_approval_request_contract import _approval_fixture


@pytest.mark.unit
async def test_canonical_sandbox_reads_pass_approved_read_only_guard(
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    test_engine,
    staged,  # noqa: F811
):
    body, _, _ = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "read_only"
    )
    monkeypatch.setattr(
        runtime_model_route,
        "load_workspace_policy",
        AsyncMock(return_value={"permission_mode": "ask"}),
    )
    receipt = await plans.approve_plan_and_start(body, SimpleNamespace(), test_user, test_db)
    await asyncio.sleep(0)
    run_id = receipt["run"]["id"]
    names = (
        "read",
        "batch_read",
        "list",
        "glob",
        "grep",
        "ls",
        "unknown_read",
        "read_secret_mutation",
    )
    port = SimpleNamespace(call_tool=AsyncMock(side_effect=AssertionError("No network allowed")))
    tools = {
        name: create_sandbox_mcp_tool(
            "qa-sandbox", name, {"input_schema": {"type": "object"}}, port
        )
        for name in names
    }
    catalog = ToolSetCatalogV2()
    catalog.register_tools(
        "real-sandbox-factory",
        lambda **kwargs: ToolSetV2(tools=tools, definitions=tuple(convert_tools(tools))),
    )
    selected = catalog.resolve(
        agent=SimpleNamespace(), selection_context=None, prepared_tool_provider=None
    )
    manager, _ = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="approved-read-metadata",
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
        for definition in selected.definitions:
            if definition.name in names[:6]:
                await require_approved_run_tool_permission_v2(definition.permission, required=True)
                assert definition.permission == "read"
            else:
                with pytest.raises(RuntimeV2Error):
                    await require_approved_run_tool_permission_v2(
                        definition.permission, required=True
                    )
    port.call_tool.assert_not_called()
