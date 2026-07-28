"""Tests for bounded structured fields returned by sandbox MCP tools."""

from types import SimpleNamespace

from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)


def test_file_browser_fields_survive_the_websocket_result_adapter() -> None:
    result = SimpleNamespace(
        content=[{"type": "text", "text": "listed"}],
        isError=False,
        artifact=None,
        model_extra=None,
        metadata={
            "listing": {"contract_version": 1},
            "file": {"contract_version": 1},
            "download": {"contract_version": 1},
            "reason_code": "sandbox_file_not_found",
            "untrusted_extra": {"secret": True},
        },
    )

    payload = MCPSandboxAdapter._build_tool_success_result(result)

    assert payload["listing"] == {"contract_version": 1}
    assert payload["file"] == {"contract_version": 1}
    assert payload["download"] == {"contract_version": 1}
    assert payload["reason_code"] == "sandbox_file_not_found"
    assert "untrusted_extra" not in payload
