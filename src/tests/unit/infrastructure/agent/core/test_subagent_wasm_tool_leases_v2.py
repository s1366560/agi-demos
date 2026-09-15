"""Real signed WASM leases must survive an authorized detached operation boundary."""

import json

import pytest

from src.infrastructure.agent.core.subagent_tool_set_v2 import SubAgentToolSetBindingV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2
from src.tests.unit.application.services.test_wasm_operation_authority_v2 import (
    setup_authority,  # noqa: F401
    verified,  # noqa: F401
)
from src.tests.unit.infrastructure.agent.core.test_subagent_tool_set_inheritance_v2 import (
    _react_agent,
    _subagent,
)
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (
    SCOPE,
    Authority,
    resolve,
    staged,  # noqa: F401
)


async def _prepare(agent, worker, inherited):
    return await agent._session_runner._prepare_child_tool_definitions(
        subagent=worker,
        available_subagents=[worker],
        conversation_context=[],
        project_id=SCOPE.project_id,
        tenant_id=SCOPE.tenant_id,
        conversation_id=SCOPE.session_id,
        abort_signal=None,
        delegation_depth=0,
        inherited_tool_set=inherited,
    )


@pytest.mark.parametrize("allowed_tools", [["*"], [], ["unavailable"]])
async def test_child_wasm_uses_independent_lease_and_exact_child_allowlist(staged, allowed_tools):  # noqa: F811
    manager, catalog = staged
    authority = Authority()
    worker = _subagent("worker", allowed_tools=allowed_tools)
    agent, _ = _react_agent(tools={}, subagents=[worker])
    async with pin_operation_context_v2(manager, operation_id="parent", scope=SCOPE) as parent:
        await prepare_wasm_operation_tools_v2(parent, authority)
        inherited = SubAgentToolSetBindingV2(operation=parent).bind(resolve(catalog))
        async with pin_operation_context_v2(manager, operation_id="child", scope=SCOPE):
            tools = await _prepare(agent, worker, inherited)
            if allowed_tools != ["*"]:
                assert tools == []
                return
            (tool,) = tools
            assert json.loads(await tool.execute(input="child"))["score"] == 20260914
            # Parent disposal must revoke only its own callable, not the child lease.
            await parent.dispose()
            assert json.loads(await tool.execute(input="after parent"))["score"] == 20260914
            authority.allowed = False
            with pytest.raises(RuntimeV2Error, match="permission"):
                await tool.execute(input="revoked grant")
        with pytest.raises(RuntimeV2Error, match="no longer active"):
            await tool.execute(input="disposed child")


async def test_detached_child_fresh_sql_grant_and_revoke(setup_authority, test_db, verified):  # noqa: F811
    manager, catalog, authority, scope, identity, governance, _ = setup_authority
    worker = _subagent("worker", allowed_tools=["*"])
    agent, _ = _react_agent(tools={}, subagents=[worker])
    services = {OPERATION_IDENTITY_SERVICE_V2: identity}
    async with pin_operation_context_v2(
        manager, operation_id="sql-parent", scope=scope, services=services
    ) as parent:
        await prepare_wasm_operation_tools_v2(parent, authority)
        inherited = SubAgentToolSetBindingV2(operation=parent).bind(resolve(catalog))
        async with pin_operation_context_v2(
            manager, operation_id="sql-child", scope=scope, services=services
        ):
            (tool,) = await _prepare(agent, worker, inherited)
            assert json.loads(await tool.execute(input="authorized child"))["score"] == 20260914
            await governance.revoke_permissions(verified.manifest.bundle_id)
            await test_db.commit()
            with pytest.raises(RuntimeV2Error, match="permission"):
                await tool.execute(input="revoked child")
        async with pin_operation_context_v2(
            manager, operation_id="sql-new-child", scope=scope, services=services
        ):
            assert await _prepare(agent, worker, inherited) == []


async def test_child_cannot_expand_empty_parent_tool_set(staged):  # noqa: F811
    manager, catalog = staged
    authority = Authority()
    authority.allowed = False
    worker = _subagent("worker", allowed_tools=["*"])
    agent, _ = _react_agent(tools={}, subagents=[worker])
    async with pin_operation_context_v2(
        manager, operation_id="parent-denied", scope=SCOPE
    ) as parent:
        assert await prepare_wasm_operation_tools_v2(parent, authority) == 0
        inherited = SubAgentToolSetBindingV2(operation=parent).bind(resolve(catalog))
        authority.allowed = True
        async with pin_operation_context_v2(manager, operation_id="child-denied", scope=SCOPE):
            assert await _prepare(agent, worker, inherited) == []


async def test_child_cannot_rebind_wasm_across_scope(staged):  # noqa: F811
    from dataclasses import replace

    manager, catalog = staged
    worker = _subagent("worker", allowed_tools=["*"])
    agent, _ = _react_agent(tools={}, subagents=[worker])
    async with pin_operation_context_v2(
        manager, operation_id="parent-scope", scope=SCOPE
    ) as parent:
        await prepare_wasm_operation_tools_v2(parent, Authority())
        inherited = SubAgentToolSetBindingV2(operation=parent).bind(resolve(catalog))
        async with pin_operation_context_v2(
            manager, operation_id="child-scope", scope=replace(SCOPE, session_id="other-session")
        ):
            with pytest.raises(RuntimeV2Error, match="scope or generation differs"):
                await _prepare(agent, worker, inherited)
