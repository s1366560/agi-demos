"""Canonical SQL approval through real authenticated MCP file I/O (no model)."""

from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent import runtime_model_route
from src.application.services.approved_run_tool_permission_v2 import prepare_approved_run_guard_v2
from src.application.services.chat_run_tool_permission_v2 import prepare_chat_run_guard_v2
from src.application.services.workspace_file_permission_v2 import require_workspace_file_binding_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.sandbox_port import SandboxStatus
from src.infrastructure.adapters.primary.web.routers.agent import plans
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.sandbox_tool_wrapper import create_sandbox_mcp_tool
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient
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

_SERVER = """
import asyncio, json, sys
from src.server.websocket_server import MCPWebSocketServer, AuthConfig
from src.tools.file_tools import create_write_tool
from src.tools import confined_workspace_write
from pathlib import Path
assert Path(confined_workspace_write.__file__).resolve() == Path("/app/src/tools/confined_workspace_write.py")
assert confined_workspace_write.workspace_mount_id("/workspace") is not None
async def main():
    cfg = json.loads(sys.stdin.readline())
    server = MCPWebSocketServer(host="0.0.0.0",port=8765,workspace_dir=cfg["root"],auth_config=AuthConfig(enabled=True,static_token=cfg["token"]))
    server.register_tool(create_write_tool())
    await server.start()
    print(server._site._server.sockets[0].getsockname()[1],flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()
asyncio.run(main())
"""


@pytest_asyncio.fixture(loop_scope="function")
async def real_file_server(tmp_path):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    token = secrets.token_hex(32)
    repository = Path(__file__).resolve().parents[5]
    container_name = "agistack-confined-test-" + secrets.token_hex(8)
    process = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        container_name,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "-p",
        "127.0.0.1::8765",
        "-v",
        f"{root}:/workspace",
        "-v",
        f"{repository / 'sandbox-mcp-server/src'}:/app/src:ro",
        "-w",
        "/app",
        "--entrypoint",
        "python",
        "sandbox-mcp-server:latest",
        "-c",
        _SERVER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    client = None
    try:
        process.stdin.write((json.dumps({"root": "/workspace", "token": token}) + "\n").encode())
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), 10)
        assert int(line.decode().strip()) == 8765
        mapping = await asyncio.to_thread(
            subprocess.check_output, ["docker", "port", container_name, "8765/tcp"], text=True
        )
        port = int(mapping.strip().rsplit(":", 1)[1])
        client = MCPWebSocketClient(
            url=f"ws://127.0.0.1:{port}",
            headers={"Authorization": f"Bearer {token}"},
            heartbeat_interval=None,
            timeout=10,
        )
        assert await client.connect()
        schemas = await client.list_tools()
        schema = next(value for value in schemas if value.name == "write")
        assert schema.meta["memstack/workspace-write"]["contract"] == "directory-fd-write-v1"
        yield (
            root,
            client,
            {
                "name": schema.name,
                "description": schema.description,
                "input_schema": schema.inputSchema,
                "_meta": schema.meta,
            },
        )
    finally:
        if client is not None:
            await client.disconnect()
        await asyncio.to_thread(
            subprocess.run, ["docker", "rm", "-f", container_name], capture_output=True, check=False
        )
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.wait(), 10)


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("run_kind", ["plan", "chat"])
@pytest.mark.parametrize(
    "case",
    [
        "inside",
        "outside",
        "symlink",
        "other_sandbox",
        "other_project",
        "undeclared",
        "policy_revoked",
    ],
)
async def test_real_workspace_write_is_confined_to_approved_environment(  # noqa: PLR0915
    monkeypatch,
    test_db,
    test_user,
    test_project_db,
    test_engine,
    staged,  # noqa: F811
    real_file_server,
    pipeline,
    case,
    run_kind,
):
    root, client, schema = real_file_server
    body, _, environment = await _approval_fixture(
        monkeypatch, test_db, test_user, test_project_db, "workspace_write"
    )
    environment.return_value = {
        "id": "real-sandbox",
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
    if run_kind == "chat":
        monkeypatch.setattr(
            "src.application.services.chat_permission_admission_v2.load_workspace_policy",
            AsyncMock(return_value={"revision": 3, "permission_mode": "automatic"}),
        )
        conversation = Conversation(
            id="mount-chat-conversation",
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            user_id=test_user.id,
            title="Mount binding",
            current_mode="build",
            workspace_id="mount-workspace",
        )
        test_db.add(conversation)
        await test_db.commit()
        run = await ensure_chat_run_authority(
            test_db,
            conversation=conversation,
            run_id="mount-chat-run",
            request_message="Write within bound workspace",
            client_message_id="mount-chat-turn",
            app_model_context=None,
            permission_mode="automatic",
        )
        run_id = run.id
        body = body.model_copy(update={"conversation_id": conversation.id})
    calls = []
    sandbox_id = "other-sandbox" if case == "other_sandbox" else "real-sandbox"
    instance = SimpleNamespace(
        id=sandbox_id,
        status=SandboxStatus.RUNNING,
        labels={
            "memstack.tenant_id": test_project_db.tenant_id,
            "memstack.project_id": "foreign" if case == "other_project" else test_project_db.id,
        },
    )

    async def call_tool(_sandbox, name, arguments, **_kwargs):
        calls.append(name)
        result = await client.call_tool(name, arguments)
        return {"content": result.content, "isError": result.isError, "metadata": result.metadata}

    async def get_sandbox(_sandbox_id):
        if case == "policy_revoked":
            monkeypatch.setattr(
                runtime_model_route,
                "load_workspace_policy",
                AsyncMock(return_value={"permission_mode": "ask"}),
            )
            monkeypatch.setattr(
                "src.application.services.chat_permission_admission_v2.load_workspace_policy",
                AsyncMock(return_value={"revision": 4, "permission_mode": "ask"}),
            )
        return instance

    port = SimpleNamespace(get_sandbox=get_sandbox, call_tool=call_tool)
    if case == "undeclared":
        schema = {key: value for key, value in schema.items() if key != "_meta"}
    tool = create_sandbox_mcp_tool(sandbox_id, "write", schema, port)
    definition = convert_tools({"write": tool})[0]
    arguments = {"file_path": "marker.txt", "content": "real scoped UTF8 内容"}
    external = root.parent / "external.txt"
    external.write_text("unchanged")
    if case == "outside":
        arguments["file_path"] = str(external)
    if case == "symlink":
        (root / "link").symlink_to(root.parent, target_is_directory=True)
        arguments["file_path"] = "link/external.txt"
    manager, _ = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="real-workspace-io",
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
        prepare = prepare_chat_run_guard_v2 if run_kind == "chat" else prepare_approved_run_guard_v2
        await prepare(
            operation, run_id, sessions=async_sessionmaker(test_engine, expire_on_commit=False)
        )
        if run_kind == "chat" and case == "other_sandbox":
            initial = SimpleNamespace(
                id="real-sandbox",
                status=SandboxStatus.RUNNING,
                labels={
                    "memstack.tenant_id": test_project_db.tenant_id,
                    "memstack.project_id": test_project_db.id,
                },
            )
            await require_workspace_file_binding_v2(
                sandbox_id="real-sandbox",
                workspace_root="/workspace",
                sandbox_port=SimpleNamespace(get_sandbox=AsyncMock(return_value=initial)),
            )
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="never-called",
                run_id=run_id,
                approved_run_required=run_kind == "plan",
                chat_run_required=run_kind == "chat",
            ),
            tools=[definition],
        )
        processor._langfuse_context = {
            "conversation_id": body.conversation_id,
            "project_id": test_project_db.id,
            "tenant_id": test_project_db.tenant_id,
            "user_id": test_user.id,
        }

        if pipeline:
            processor._tool_pipeline = ToolPipeline(
                permission_manager=processor.permission_manager,
                doom_detector=processor.doom_loop_detector,
                truncator=OutputTruncator(),
                hooks=ToolHookRegistry(),
            )
        part = ToolPart(call_id="io", tool="write", status=ToolState.RUNNING)
        processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
        processor._pending_tool_calls["io"] = part
        events = [
            event
            async for event in processor._execute_tool(
                body.conversation_id, "io", "write", arguments
            )
        ]
    assert events
    if case == "inside":
        assert part.status == ToolState.COMPLETED, part.error
        assert (root / "marker.txt").read_text() == "real scoped UTF8 内容"
        async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
            persisted = await db.get(AgentRunAuthorityModel, run_id)
            assert persisted.authorization_snapshot["environment"]["id"] == "real-sandbox"
            assert persisted.authorization_snapshot["environment"]["workspace_path"] == "/workspace"
        assert calls == ["write"]
    else:
        assert part.status == ToolState.ERROR
        assert not (root / "marker.txt").exists()
        if case != "symlink":
            assert calls == []
    assert external.read_text() == "unchanged"
