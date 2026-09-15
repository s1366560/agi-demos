"""A confined mutation never repeats an ambiguous transport result."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.mcp_errors import RetryConfig
from src.infrastructure.agent.tools.sandbox_tool_wrapper import _execute_with_retry
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.mark.unit
@pytest.mark.parametrize("revoked", [False, True])
async def test_confined_write_rechecks_authority_and_never_retries(monkeypatch, revoked):
    check = AsyncMock(side_effect=RuntimeV2Error("revoked", "Revoked") if revoked else None)
    monkeypatch.setattr(
        "src.application.services.workspace_file_permission_v2.require_workspace_file_binding_v2",
        check,
    )
    # Timeout can mean the server applied append and the response was lost.
    call = AsyncMock(side_effect=TimeoutError("response unavailable"))
    with pytest.raises(RuntimeError):
        await _execute_with_retry(
            sandbox_id="bound-sandbox",
            tool_name="write",
            sandbox_port=SimpleNamespace(call_tool=call),
            retry_config=RetryConfig(max_retries=3),
            kwargs={
                "file_path": "a.txt",
                "content": "one",
                "mode": "append",
                "_workspace_dir": "/workspace",
                "_workspace_write_contract": "directory-fd-write-v1",
            },
        )
    check.assert_awaited_once()
    assert call.await_count == (0 if revoked else 1)
