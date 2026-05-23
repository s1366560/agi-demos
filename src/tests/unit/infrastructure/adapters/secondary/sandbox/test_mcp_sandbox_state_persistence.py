from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.agent.workspace.manifest import WorkspaceManifest


@pytest.mark.unit
class TestMCPSandboxStatePersistence:
    async def test_persist_sandbox_state_writes_redis_and_manifest(self, tmp_path) -> None:
        redis_client = AsyncMock()
        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter(workspace_base=str(tmp_path), redis_client=redis_client)

        await adapter._persist_sandbox_state("sandbox-1", "running", "project-1")

        redis_client.hset.assert_awaited_once()
        hset_call = redis_client.hset.await_args
        assert hset_call.args == ("sandbox:state:sandbox-1",)
        assert hset_call.kwargs["mapping"]["sandbox_id"] == "sandbox-1"
        assert hset_call.kwargs["mapping"]["state"] == "running"
        assert hset_call.kwargs["mapping"]["project_id"] == "project-1"
        redis_client.sadd.assert_awaited_once_with(
            "project:project-1:sandboxes", "sandbox-1"
        )

        manifest = WorkspaceManifest.load(tmp_path / "project-1")
        assert manifest is not None
        assert manifest.last_sandbox_id == "sandbox-1"
        assert manifest.last_sandbox_state == "running"

    async def test_persist_sandbox_state_keeps_manifest_fallback_when_redis_fails(
        self, tmp_path
    ) -> None:
        redis_client = AsyncMock()
        redis_client.hset.side_effect = RuntimeError("redis unavailable")
        with patch("docker.from_env"):
            adapter = MCPSandboxAdapter(workspace_base=str(tmp_path), redis_client=redis_client)

        await adapter._persist_sandbox_state("sandbox-2", "terminated", "project-2")

        manifest = WorkspaceManifest.load(tmp_path / "project-2")
        assert manifest is not None
        assert manifest.last_sandbox_id == "sandbox-2"
        assert manifest.last_sandbox_state == "terminated"
