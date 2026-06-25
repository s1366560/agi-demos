import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest
from acp.exceptions import RequestError

from src.infrastructure.acp.cli import (
    _acp_websocket_url,
    _inject_default_project_id,
    _reject_all_stdin,
    _request_id,
    _request_metadata,
)
from src.infrastructure.acp.client import (
    ExternalACPAgentConfig,
    ExternalACPAgentService,
    ExternalACPPromptResult,
    load_external_agent_configs,
)


def test_load_external_agent_configs_from_json(tmp_path) -> None:
    config_path = tmp_path / "agents.json"
    config_path.write_text(
        """
        {
          "agents": [
            {
              "id": "local",
              "name": "Local Agent",
              "transport": "stdio",
              "command": "agent",
              "args": ["--stdio"],
              "env": {"API_KEY": "LOCAL_AGENT_API_KEY"}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    configs = load_external_agent_configs(str(config_path))

    assert configs[0].id == "local"
    assert configs[0].env == {"API_KEY": "LOCAL_AGENT_API_KEY"}


def test_external_agent_summary_reports_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("LOCAL_AGENT_API_KEY", raising=False)
    service = ExternalACPAgentService(
        load_external_agent_configs(
            _fixture_config(
                {
                    "agents": [
                        {
                            "id": "local",
                            "name": "Local Agent",
                            "transport": "stdio",
                            "command": "agent",
                            "env": {"API_KEY": "LOCAL_AGENT_API_KEY"},
                        }
                    ]
                }
            )
        )
    )

    summary = service.list_agents()[0]

    assert not summary.available
    assert summary.missing_env == ["LOCAL_AGENT_API_KEY"]


def test_external_agent_summary_available_when_env_present(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_AGENT_API_KEY", "secret")
    service = ExternalACPAgentService(
        load_external_agent_configs(
            _fixture_config(
                {
                    "agents": [
                        {
                            "id": "local",
                            "name": "Local Agent",
                            "transport": "stdio",
                            "command": "agent",
                            "env": {"API_KEY": "LOCAL_AGENT_API_KEY"},
                        }
                    ]
                }
            )
        )
    )

    summary = service.list_agents()[0]

    assert summary.available
    assert summary.missing_env == []


def test_stdio_bridge_url_resolution() -> None:
    assert _acp_websocket_url("http://127.0.0.1:8000") == "ws://127.0.0.1:8000/api/v1/acp/ws"
    assert _acp_websocket_url("https://memstack.test/base") == (
        "wss://memstack.test/base/api/v1/acp/ws"
    )
    assert _acp_websocket_url("ws://localhost:8000/api/v1/acp/ws") == (
        "ws://localhost:8000/api/v1/acp/ws"
    )


def test_request_id_extracts_only_json_rpc_requests() -> None:
    assert _request_id('{"jsonrpc":"2.0","id":1,"method":"initialize"}') == 1
    assert _request_id('{"jsonrpc":"2.0","method":"session/cancel"}') is None
    assert _request_id("not-json") is None


def test_request_metadata_extracts_session_close_method() -> None:
    assert _request_metadata(
        '{"jsonrpc":"2.0","id":"close-1","method":"session/close","params":{}}'
    ) == ("close-1", "session/close")


def test_stdio_bridge_injects_default_project_id(monkeypatch) -> None:
    monkeypatch.setenv("ACP_DEFAULT_PROJECT_ID", "project-1")

    line = _inject_default_project_id(
        '{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/tmp"}}'
    )

    payload = json.loads(line)
    assert payload["params"]["_meta"]["memstack"]["projectId"] == "project-1"


def test_stdio_bridge_preserves_explicit_project_id(monkeypatch) -> None:
    monkeypatch.setenv("ACP_DEFAULT_PROJECT_ID", "project-1")

    line = _inject_default_project_id(
        '{"jsonrpc":"2.0","id":2,"method":"session/new",'
        '"params":{"cwd":"/tmp","_meta":{"memstack":{"projectId":"project-2"}}}}'
    )

    payload = json.loads(line)
    assert payload["params"]["_meta"]["memstack"]["projectId"] == "project-2"


async def test_stdio_bridge_reject_handles_closed_stdin(monkeypatch) -> None:
    class ClosedStdin:
        @property
        def buffer(self) -> object:
            raise ValueError("I/O operation on closed file.")

        def readline(self) -> str:
            raise ValueError("I/O operation on closed file.")

    monkeypatch.setattr(sys, "stdin", ClosedStdin())

    await _reject_all_stdin(RequestError.internal_error({"details": "closed"}))


async def test_external_agent_prompt_timeout_cancels_transport(monkeypatch) -> None:
    class SlowTransport:
        def __init__(self) -> None:
            self.cancelled = False

        async def initialize(self) -> None:
            return None

        async def new_session(
            self,
            *,
            cwd: str,
            additional_directories: list[str] | None,
            mcp_servers: list[dict],
            field_meta: dict | None = None,
        ) -> str:
            del cwd, additional_directories, mcp_servers, field_meta
            return "remote-session"

        async def prompt(
            self,
            *,
            remote_session_id: str,
            prompt: list[dict],
            message_id: str | None,
        ) -> ExternalACPPromptResult:
            del remote_session_id, prompt, message_id
            await asyncio.sleep(60)
            return ExternalACPPromptResult()

        async def cancel(self, remote_session_id: str) -> None:
            del remote_session_id
            self.cancelled = True

        async def close(self, remote_session_id: str) -> None:
            del remote_session_id

    monkeypatch.setattr(
        "src.infrastructure.acp.client.get_settings",
        lambda: SimpleNamespace(acp_external_prompt_timeout_seconds=0.01),
    )
    service = ExternalACPAgentService(
        [
            ExternalACPAgentConfig(
                id="slow",
                name="Slow Agent",
                transport="stdio",
                command="slow-agent",
            )
        ]
    )
    transport = SlowTransport()
    monkeypatch.setattr(service, "_build_transport", lambda _config: transport)

    session = await service.new_session(
        agent_id="slow",
        owner_user_id="user-1",
        cwd="/tmp",
        additional_directories=None,
        mcp_servers=[],
    )

    with pytest.raises(TimeoutError, match="session/prompt timed out"):
        await service.prompt(
            agent_id="slow",
            session_id=session.session_id,
            owner_user_id="user-1",
            prompt=[{"type": "text", "text": "hello"}],
            message_id="message-1",
        )

    assert transport.cancelled
    assert service.list_agents()[0].last_error == "session/prompt timed out after 0.01s"


def _fixture_config(payload: dict) -> str:
    import json
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path
