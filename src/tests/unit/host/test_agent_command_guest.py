"""Agent commands run in a child process and do not keep host_operation."""

import json
from pathlib import Path

import pytest

from plugins.business.agent.guest.dispatch import TOOLS
from src.host.operations.agent_package.runtime import run_agent_command

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]


def test_agent_contributions_have_no_host_operation() -> None:
    document = json.loads((ROOT / "plugins/business/agent/contributions.json").read_text())
    assert document["commands"]
    assert all("host_operation" not in command for command in document["commands"])
    tools = {tool["name"] for tool in document["tools"]}
    for command in document["commands"]:
        if command["id"] == "validate-skill":
            assert command["tool"] == "validate_skill"
            continue
        assert command["tool"] in TOOLS
        assert command["tool"] in tools
        assert "tools.execute" in next(
            tool["permissions"] for tool in document["tools"] if tool["name"] == command["tool"]
        )


async def test_guest_process_lists_conversations_without_the_parent_pid() -> None:
    class Scope:
        tenant_id = "t"
        project_id = "p"

    class User:
        id = "u"

    class Request:
        app = None

    class Application:
        request = Request()
        db = None
        user = User()
        scope = Scope()

    calls: list[str] = []

    async def http(self, method, path, **kwargs):  # type: ignore[no-untyped-def]
        del self, kwargs
        calls.append(method + " " + path)
        return {"items": [{"id": "c", "title": "Guest", "execution_target": "cloud"}]}

    async def local_ids(self, ids):  # type: ignore[no-untyped-def]
        del self
        assert ids == ["c"]
        return []

    from src.host.operations.agent_package import bridge as bridge_module

    original_http = bridge_module.HostBridge.http
    original_local = bridge_module.HostBridge.local_ids
    bridge_module.HostBridge.http = http  # type: ignore[method-assign]
    bridge_module.HostBridge.local_ids = local_ids  # type: ignore[method-assign]
    try:
        result = await run_agent_command(Application(), "app.agent.list", {}, None)
    finally:
        bridge_module.HostBridge.http = original_http  # type: ignore[method-assign]
        bridge_module.HostBridge.local_ids = original_local  # type: ignore[method-assign]
    assert result["items"][0]["title"] == "Guest"
    assert calls == ["GET conversations"]


async def test_guest_process_returns_a_transcript_larger_than_the_default_pipe_limit() -> None:
    class Scope:
        tenant_id = "t"
        project_id = "p"

    class User:
        id = "u"

    class Request:
        app = None

    class Application:
        request = Request()
        db = None
        user = User()
        scope = Scope()

    title = "话" * 40_000

    async def http(self, method, path, **kwargs):  # type: ignore[no-untyped-def]
        del self, method, path, kwargs
        return {"items": [{"id": "c", "title": title, "execution_target": "cloud"}]}

    async def local_ids(self, ids):  # type: ignore[no-untyped-def]
        del self, ids
        return []

    from src.host.operations.agent_package import bridge as bridge_module

    original_http = bridge_module.HostBridge.http
    original_local = bridge_module.HostBridge.local_ids
    bridge_module.HostBridge.http = http  # type: ignore[method-assign]
    bridge_module.HostBridge.local_ids = local_ids  # type: ignore[method-assign]
    try:
        result = await run_agent_command(Application(), "app.agent.list", {}, None)
    finally:
        bridge_module.HostBridge.http = original_http  # type: ignore[method-assign]
        bridge_module.HostBridge.local_ids = original_local  # type: ignore[method-assign]
    assert result["items"][0]["title"] == title


async def test_standalone_kernel_forwards_agent_commands_before_starting_a_guest(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from src.infrastructure.plugins.v2.project_package_execution import dispatch_project_command
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

    forwarded = []

    async def fake_forward(origin, ctx, **kwargs):  # type: ignore[no-untyped-def]
        del ctx
        forwarded.append((origin, kwargs["command"]))
        return {"items": []}

    async def fail_local(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("local guest started")

    monkeypatch.setattr("src.host.operations.agent_package.runtime.run_agent_command", fail_local)
    scope = ScopeBindingV2(tenant_id="t", project_id="p")
    command = SimpleNamespace(
        command_id="chat-list",
        permissions=frozenset({"app.agent.list"}),
        accepts_input=True,
        payload={},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        tool="agent.chat-list",
        host_operation=None,
    )
    package = SimpleNamespace(
        plugin_id="memstack-agent",
        digest="sha256:" + "a" * 64,
        approved_permissions=frozenset({"app.agent.list"}),
        contribution=SimpleNamespace(commands=(command,)),
    )
    application = SimpleNamespace(
        request=SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(package_application_runtime_origin="http://127.0.0.1:9")
            ),
            headers={},
        ),
        scope=scope,
    )
    # The dispatch imports forward_command lazily, so patch the module it imports.
    import src.host.operations.remote_application_commands as remote

    monkeypatch.setattr(remote, "forward_command", fake_forward)
    assert await dispatch_project_command(
        package, scope, "chat-list", {}, application=application
    ) == {"items": []}
    assert forwarded == [("http://127.0.0.1:9", "chat-list")]
