"""MCP initialize negotiates the stable revision and rejects the rest."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from src.infrastructure.mcp.protocol import (
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    UnsupportedProtocolVersionError,
    accept_server_protocol,
    negotiate_client_offer,
)


def test_latest_stable_revision_is_offered_and_older_supported_revisions_remain() -> None:
    assert LATEST_PROTOCOL_VERSION == "2026-07-28"
    assert negotiate_client_offer("2026-07-28") == "2026-07-28"
    assert negotiate_client_offer("2024-11-05") == "2024-11-05"
    assert accept_server_protocol("2025-03-26") == "2025-03-26"


def test_unknown_revision_is_rejected() -> None:
    with pytest.raises(UnsupportedProtocolVersionError, match="unsupported_protocol_version"):
        negotiate_client_offer("1999-01-01")
    with pytest.raises(UnsupportedProtocolVersionError):
        accept_server_protocol(None)


def test_stdio_child_process_negotiates_and_rejects() -> None:
    script = textwrap.dedent(
        """
        import json, sys
        line = sys.stdin.readline()
        request = json.loads(line)
        offered = request["params"]["protocolVersion"]
        supported = {
            "2026-07-28", "2026-01-26", "2025-11-25",
            "2025-06-18", "2025-03-26", "2024-11-05",
        }
        if offered not in supported:
            body = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32602,
                    "message": "unsupported_protocol_version: " + offered,
                },
            }
        else:
            body = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocolVersion": offered,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "protocol-fixture", "version": "1"},
                },
            }
        sys.stdout.write(json.dumps(body) + "\\n")
        sys.stdout.flush()
        """
    )
    offered = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "negotiation-test", "version": "1"},
        },
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(offered) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["result"]["protocolVersion"] == "2026-07-28"
    assert result["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert "sampling" not in result["result"]["capabilities"]
    assert set(SUPPORTED_PROTOCOL_VERSIONS) >= {"2026-07-28", "2024-11-05"}
