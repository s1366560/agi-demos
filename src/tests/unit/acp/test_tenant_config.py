from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.infrastructure.acp.client import ExternalACPAgentConfig, ExternalACPAgentService
from src.infrastructure.adapters.primary.web.routers.acp import (
    ACPConfigValue,
    _runtime_config_from_row,
    _store_config_values,
    _stored_config_values_for_response,
)


class FakeTransport:
    initialized = False
    closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def new_session(
        self,
        *,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        field_meta: dict[str, Any] | None = None,
    ) -> str:
        assert cwd == "/tmp"
        assert additional_directories is None
        assert mcp_servers == []
        assert field_meta == {"memstack": {"projectId": "project-1"}}
        return "remote-1"

    async def prompt(
        self,
        *,
        remote_session_id: str,
        prompt: list[dict[str, Any]],
        message_id: str | None,
    ) -> Any:
        assert remote_session_id == "remote-1"
        assert prompt == [{"type": "text", "text": "hello"}]
        assert message_id is None
        return SimpleNamespace(result={}, updates=[{"update": {"content": {"type": "text", "text": "ok"}}}])

    async def cancel(self, remote_session_id: str) -> None:
        assert remote_session_id == "remote-1"

    async def close(self, remote_session_id: str) -> None:
        assert remote_session_id == "remote-1"
        self.closed = True


def test_tenant_config_secret_values_are_encrypted_masked_and_resolved() -> None:
    stored = _store_config_values(
        {
            "API_KEY": ACPConfigValue(type="secret", value="plain-secret"),
            "PATH_REF": ACPConfigValue(type="env_ref", value="LOCAL_PATH_ENV"),
        },
        None,
    )

    assert stored["API_KEY"]["value"] != "plain-secret"
    masked = _stored_config_values_for_response(stored)
    assert masked["API_KEY"].type == "secret"
    assert masked["API_KEY"].has_value is True
    assert masked["API_KEY"].value == "__MEMSTACK_SECRET_UNCHANGED__"
    assert masked["PATH_REF"].value == "LOCAL_PATH_ENV"

    preserved = _store_config_values(
        {"API_KEY": ACPConfigValue(type="secret", value="__MEMSTACK_SECRET_UNCHANGED__")},
        stored,
    )
    assert preserved["API_KEY"]["value"] == stored["API_KEY"]["value"]

    runtime = _runtime_config_from_row(
        SimpleNamespace(
            agent_key="agent-1",
            name="Agent",
            transport="stdio",
            command="agent",
            args=[],
            url=None,
            env=stored,
            headers={},
            enabled=True,
        )
    )
    assert runtime.env_values["API_KEY"] == "plain-secret"
    assert runtime.env["PATH_REF"] == "LOCAL_PATH_ENV"


async def test_tenant_agent_service_tracks_metrics(monkeypatch) -> None:
    service = ExternalACPAgentService([])
    service.set_tenant_configs(
        "tenant-1",
        [
            ExternalACPAgentConfig(
                id="agent-1",
                name="Agent",
                transport="stdio",
                command="agent",
                source="tenant",
            )
        ],
    )
    fake_transport = FakeTransport()
    monkeypatch.setattr(service, "_build_transport", lambda _config: fake_transport)

    created = await service.new_session(
        agent_id="agent-1",
        owner_user_id="user-1",
        cwd="/tmp",
        additional_directories=None,
        mcp_servers=[],
        tenant_id="tenant-1",
        field_meta={"memstack": {"projectId": "project-1"}},
    )
    assert created.remote_session_id == "remote-1"

    prompt = await service.prompt(
        agent_id="agent-1",
        session_id=created.session_id,
        owner_user_id="user-1",
        prompt=[{"type": "text", "text": "hello"}],
        message_id=None,
        tenant_id="tenant-1",
    )
    assert len(prompt.updates) == 1

    summary = service.list_agents(tenant_id="tenant-1")[0]
    assert summary.active_sessions == 1
    assert summary.total_sessions == 1
    assert summary.prompt_count == 1
    assert summary.update_count == 1
    assert summary.last_error is None
    assert service.recent_events(tenant_id="tenant-1")[0].action == "session/prompt"

    await service.close(
        agent_id="agent-1",
        session_id=created.session_id,
        owner_user_id="user-1",
        tenant_id="tenant-1",
    )
    assert fake_transport.closed is True
    assert service.list_agents(tenant_id="tenant-1")[0].active_sessions == 0
