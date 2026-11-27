"""Workspace, Knowledge, Automation, Environments, and Billing leave the host process."""

import json
from pathlib import Path

import pytest

from src.host.operations.business_guest.runtime import run_business_command

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]
CONTRIBUTIONS = (
    "plugins/business/workspace/contributions.json",
    "plugins/business/knowledge/workers/graph_projection/contributions.json",
    "plugins/business/automation/contributions.json",
    "plugins/business/environments/contributions.json",
    "plugins/business/billing/contributions.json",
)


def test_business_contributions_have_no_host_operation() -> None:
    from types import SimpleNamespace

    from src.host.operations.business_guest.capabilities import CAPABILITIES
    from src.host.operations.business_guest.runtime import guest_operation

    prefixes = {
        "workspace": "memstack-workspace",
        "knowledge": "memstack-knowledge",
        "automation": "memstack-automation",
        "environments": "memstack-environments",
        "billing": "memstack-billing",
    }
    for relative in CONTRIBUTIONS:
        document = json.loads((ROOT / relative).read_text())
        assert document["commands"]
        assert all("host_operation" not in command for command in document["commands"])
        tools = {tool["name"]: tool for tool in document["tools"]}
        for command in document["commands"]:
            prefix = command["tool"].split(".", 1)[0]
            if prefix not in prefixes:
                continue
            operation = guest_operation(
                prefixes[prefix], SimpleNamespace(tool=command["tool"], host_operation=None)
            )
            assert operation in CAPABILITIES
            assert "tools.execute" in tools[command["tool"]]["permissions"]


def _application():  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    return SimpleNamespace(
        request=SimpleNamespace(app=None),
        db=None,
        user=SimpleNamespace(id="u"),
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
    )


async def test_guest_process_reads_a_directory_without_a_bearer_or_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("AUTHORIZATION", "Bearer secret")
    captured: dict[str, object] = {}

    async def call(self, name, payload, progress=None):  # type: ignore[no-untyped-def]
        del self, payload, progress
        captured["name"] = name
        return {"items": [{"id": "w", "name": "Guest"}]}

    from src.host.operations.business_guest import bridge as bridge_module

    original = bridge_module.HostBridge.call
    bridge_module.HostBridge.call = call  # type: ignore[method-assign]
    real_spawn = __import__("asyncio").create_subprocess_exec

    async def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["env"] = kwargs.get("env")
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(
        "src.host.operations.business_guest.runtime.asyncio.create_subprocess_exec", spy
    )
    try:
        result = await run_business_command(
            _application(), "memstack-workspace", "app.workspace.directory.read", {}, None
        )
    finally:
        bridge_module.HostBridge.call = original  # type: ignore[method-assign]
    assert result["items"][0]["name"] == "Guest"
    assert captured["name"] == "app.workspace.directory.read"
    env = captured["env"]
    assert isinstance(env, dict)
    assert "DATABASE_URL" not in env
    assert "AUTHORIZATION" not in env
    assert "secret" not in json.dumps(env)


async def test_guest_process_returns_a_page_larger_than_the_default_pipe_limit() -> None:
    title = "话" * 40_000

    async def call(self, name, payload, progress=None):  # type: ignore[no-untyped-def]
        del self, name, payload, progress
        return {"items": [{"id": "w", "name": title}]}

    from src.host.operations.business_guest import bridge as bridge_module

    original = bridge_module.HostBridge.call
    bridge_module.HostBridge.call = call  # type: ignore[method-assign]
    try:
        result = await run_business_command(
            _application(), "memstack-knowledge", "app.knowledge.memories.read", {}, None
        )
    finally:
        bridge_module.HostBridge.call = original  # type: ignore[method-assign]
    assert result["items"][0]["name"] == title


async def test_standalone_kernel_forwards_business_commands_without_a_local_guest(
    monkeypatch: pytest.MonkeyPatch,
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

    monkeypatch.setattr(
        "src.host.operations.business_guest.runtime.run_business_command", fail_local
    )
    scope = ScopeBindingV2(tenant_id="t", project_id="p")
    command = SimpleNamespace(
        command_id="list-directory",
        permissions=frozenset({"app.workspace.directory.read"}),
        accepts_input=True,
        payload={},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        tool="workspace.list-directory",
        host_operation=None,
    )
    package = SimpleNamespace(
        plugin_id="memstack-workspace",
        digest="sha256:" + "a" * 64,
        approved_permissions=frozenset({"app.workspace.directory.read"}),
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
    import src.host.operations.remote_application_commands as remote

    monkeypatch.setattr(remote, "forward_command", fake_forward)
    assert await dispatch_project_command(
        package, scope, "list-directory", {}, application=application
    ) == {"items": []}
    assert forwarded == [("http://127.0.0.1:9", "list-directory")]


async def test_tenant_dispatch_forwards_billing_before_starting_a_guest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from src.host.operations.tenant_commands import tenant_command
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import TenantBindingV2

    forwarded = []

    async def fake_forward(origin, ctx, **kwargs):  # type: ignore[no-untyped-def]
        del ctx
        forwarded.append((origin, kwargs["command"]))
        return {"plan": "free"}

    async def fail_local(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("local guest started")

    monkeypatch.setattr(
        "src.host.operations.business_guest.runtime.run_business_command", fail_local
    )
    command = SimpleNamespace(
        command_id="tenant-account",
        permissions=frozenset({"app.billing.account.read"}),
        accepts_input=False,
        payload={},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        tool="billing.tenant-account",
        host_operation=None,
        scope="tenant",
    )
    package = SimpleNamespace(
        plugin_id="memstack-billing",
        digest="sha256:" + "b" * 64,
        approved_permissions=frozenset({"app.billing.account.read"}),
        contribution=SimpleNamespace(commands=(command,)),
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(package_application_runtime_origin="http://127.0.0.1:9")
            ),
            headers={},
        ),
        user=SimpleNamespace(id="u"),
        scope=TenantBindingV2(tenant_id="t"),
    )
    monkeypatch.setattr("src.host.operations.tenant_commands.forward_command", fake_forward)
    monkeypatch.setattr(
        "src.host.operations.tenant_commands.project_operation",
        lambda *args, **kwargs: _Audit(),
    )
    monkeypatch.setattr(
        "src.host.operations.tenant_commands.identify_signed_operation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.host.operations.tenant_commands.validate_command_document",
        lambda *args, **kwargs: None,
    )
    assert await tenant_command(ctx, package, "tenant-account", None) == {"plan": "free"}  # type: ignore[arg-type]
    assert forwarded == [("http://127.0.0.1:9", "tenant-account")]


async def test_guest_forwards_capability_progress_to_the_caller() -> None:
    from src.host.operations.business_guest.capabilities import CAPABILITIES

    events: list[dict[str, object]] = []

    async def publish(frame: dict[str, object]) -> None:
        events.append(frame)

    async def capability(_ctx, _payload, progress):  # type: ignore[no-untyped-def]
        assert progress is not None
        await progress({"content": "YQ=="})
        return {"size": 1}

    original = CAPABILITIES["app.workspace.blackboard.read"]
    CAPABILITIES["app.workspace.blackboard.read"] = capability
    try:
        result = await run_business_command(
            _application(),
            "memstack-workspace",
            "app.workspace.blackboard.read",
            {},
            publish,
        )
    finally:
        CAPABILITIES["app.workspace.blackboard.read"] = original
    assert result == {"size": 1}
    assert events == [{"content": "YQ=="}]


class _Audit:
    executor = ""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def release(self, _pkg):
        return None
