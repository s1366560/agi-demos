"""Unit tests for plugin runtime registry."""

from importlib import import_module
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    ChannelAdapterBuildContext,
    PluginSkillBuildContext,
    PluginToolBuildContext,
)


@pytest.mark.unit
def test_register_tool_factory_rejects_duplicate_plugin_name() -> None:
    """Duplicate plugin tool registrations should fail by default."""
    registry = AgentPluginRegistry()
    registry.register_tool_factory("plugin-a", lambda _ctx: {"tool_a": object()})

    with pytest.raises(ValueError):
        registry.register_tool_factory("plugin-a", lambda _ctx: {"tool_b": object()})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_tools_collects_tools_and_conflict_diagnostics() -> None:
    """Registry should collect plugin tools and report name conflicts."""
    registry = AgentPluginRegistry()

    registry.register_tool_factory(
        "plugin-a",
        lambda _ctx: {
            "plugin_tool": SimpleNamespace(name="plugin_tool"),
            "shared_tool": SimpleNamespace(name="shared_tool"),
        },
    )

    plugin_tools, diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={"shared_tool": SimpleNamespace(name="shared_tool")},
        )
    )

    assert "plugin_tool" in plugin_tools
    assert "shared_tool" not in plugin_tools
    assert any(d.code == "tool_name_conflict" for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_channel_reload_calls_registered_hooks() -> None:
    """Channel reload hooks should be invoked with summary context."""
    registry = AgentPluginRegistry()
    captured = {}

    async def _hook(context) -> None:
        captured["plan"] = context.plan_summary
        captured["dry_run"] = context.dry_run

    registry.register_channel_reload_hook("plugin-a", _hook)

    diagnostics = await registry.notify_channel_reload(plan_summary={"add": 1}, dry_run=True)

    assert diagnostics == []
    assert captured["plan"] == {"add": 1}
    assert captured["dry_run"] is True


@pytest.mark.unit
def test_register_channel_adapter_factory_rejects_duplicate_channel_type() -> None:
    """Duplicate channel adapter registrations should fail by default."""
    registry = AgentPluginRegistry()
    registry.register_channel_adapter_factory("plugin-a", "feishu", lambda _ctx: object())

    with pytest.raises(ValueError):
        registry.register_channel_adapter_factory("plugin-b", "feishu", lambda _ctx: object())


@pytest.mark.unit
def test_register_channel_adapter_factory_persists_channel_metadata() -> None:
    """Registry should expose schema metadata for channel config UIs."""
    registry = AgentPluginRegistry()
    registry.register_channel_adapter_factory(
        "plugin-a",
        "feishu",
        lambda _ctx: object(),
        config_schema={"type": "object", "required": ["app_id"]},
        config_ui_hints={"app_id": {"label": "App ID"}},
        defaults={"connection_mode": "websocket"},
        secret_paths=["app_secret"],
    )

    metadata = registry.list_channel_type_metadata()["feishu"]
    assert metadata.plugin_name == "plugin-a"
    assert metadata.config_schema == {"type": "object", "required": ["app_id"]}
    assert metadata.config_ui_hints == {"app_id": {"label": "App ID"}}
    assert metadata.defaults == {"connection_mode": "websocket"}
    assert metadata.secret_paths == ["app_secret"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_channel_adapter_uses_registered_factory() -> None:
    """Channel adapter factory should build adapter for matching channel type."""
    registry = AgentPluginRegistry()
    expected_adapter = object()
    registry.register_channel_adapter_factory(
        "plugin-a",
        "feishu",
        lambda ctx: {"adapter": expected_adapter, "app_id": ctx.channel_config.app_id},
    )

    adapter, diagnostics = await registry.build_channel_adapter(
        ChannelAdapterBuildContext(
            channel_type="feishu",
            config_model=SimpleNamespace(id="cfg-1"),
            channel_config=SimpleNamespace(app_id="cli_xxx"),
        )
    )

    assert adapter == {"adapter": expected_adapter, "app_id": "cli_xxx"}
    assert any(d.code == "channel_adapter_loaded" for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_hook_and_notify_hook_collects_diagnostics() -> None:
    """Hook handlers should run and failures should be reported as diagnostics."""
    registry = AgentPluginRegistry()
    captured: list[dict[str, object]] = []

    async def _ok_hook(payload):
        captured.append(dict(payload))

    async def _failing_hook(payload):
        raise RuntimeError("boom")

    registry.register_hook("plugin-a", "before_tool_selection", _ok_hook)
    registry.register_hook("plugin-b", "before_tool_selection", _failing_hook)

    diagnostics = await registry.notify_hook(
        "before_tool_selection",
        payload={"tenant_id": "tenant-1"},
    )

    assert len(captured) == 1
    assert captured[0]["tenant_id"] == "tenant-1"
    assert captured[0]["hook_family"] == "mutating"
    assert captured[0]["hook_identity"]["hook_name"] == "before_tool_selection"
    assert any(item.code == "hook_handler_failed" for item in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_register_command_service_provider_and_execute_command() -> None:
    """Command/service/provider registries should expose runtime extension points."""
    registry = AgentPluginRegistry()
    registry.register_service("plugin-a", "skill-index", {"version": 1})
    registry.register_provider("plugin-a", "embedding", {"provider": "demo"})

    async def _command(payload):
        return {"echo": payload.get("message")}

    registry.register_command("plugin-a", "echo", _command)

    result, diagnostics = await registry.execute_command("echo", payload={"message": "hello"})

    assert diagnostics == []
    assert result == {"echo": "hello"}
    assert registry.get_service("skill-index") == {"version": 1}
    assert registry.get_provider("embedding") == {"provider": "demo"}


@pytest.mark.unit
def test_register_skill_factory_rejects_duplicate_plugin_name() -> None:
    """Duplicate plugin skill registrations should fail by default."""
    registry = AgentPluginRegistry()
    registry.register_skill_factory("plugin-a", lambda _ctx: [{"name": "s1"}])

    with pytest.raises(ValueError):
        registry.register_skill_factory("plugin-a", lambda _ctx: [{"name": "s2"}])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_skills_collects_skills_and_diagnostics() -> None:
    """Registry should collect plugin skill dicts from all factories."""
    registry = AgentPluginRegistry()

    registry.register_skill_factory(
        "plugin-a",
        lambda _ctx: [
            {"name": "search-web", "description": "Search the web", "tools": ["web"]},
            {"name": "summarize", "description": "Summarize text", "tools": ["llm"]},
        ],
    )
    registry.register_skill_factory(
        "plugin-b",
        lambda _ctx: [
            {"name": "translate", "description": "Translate text", "tools": ["llm"]},
        ],
    )

    skills, diagnostics = await registry.build_skills(
        PluginSkillBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )

    assert len(skills) == 3
    names = {s["name"] for s in skills}
    assert names == {"search-web", "summarize", "translate"}
    assert any(d.code == "plugin_skills_loaded" for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_skills_handles_factory_failure_gracefully() -> None:
    """A failing skill factory should produce a diagnostic but not crash."""
    registry = AgentPluginRegistry()

    def _broken_factory(_ctx):
        raise RuntimeError("boom")

    registry.register_skill_factory("plugin-broken", _broken_factory)
    registry.register_skill_factory(
        "plugin-ok",
        lambda _ctx: [{"name": "ok-skill", "description": "Works", "tools": ["t"]}],
    )

    skills, diagnostics = await registry.build_skills(
        PluginSkillBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )

    # The working factory's skills should still appear
    assert len(skills) == 1
    assert skills[0]["name"] == "ok-skill"
    # The broken factory should produce an error diagnostic
    assert any(d.code == "skill_factory_failed" and "boom" in d.message for d in diagnostics)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_skills_with_async_factory() -> None:
    """Async skill factories should be awaited correctly."""
    registry = AgentPluginRegistry()

    async def _async_factory(_ctx):
        return [
            {"name": "async-skill", "description": "Async", "tools": ["tool1"]},
        ]

    registry.register_skill_factory("plugin-async", _async_factory)

    skills, diagnostics = await registry.build_skills(
        PluginSkillBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )

    assert len(skills) == 1
    assert skills[0]["name"] == "async-skill"
    assert any(d.code == "plugin_skills_loaded" for d in diagnostics)


@pytest.mark.unit
def test_list_well_known_hooks_returns_documented_names() -> None:
    """WELL_KNOWN_HOOKS should contain expected lifecycle hook names."""
    hooks = AgentPluginRegistry.list_well_known_hooks()
    assert isinstance(hooks, frozenset)
    expected_subset = {
        "before_prompt_build",
        "before_tool_selection",
        "after_tool_execution",
        "after_turn_complete",
        "before_response",
        "on_error",
        "on_session_start",
        "on_session_end",
    }
    assert expected_subset.issubset(hooks)


@pytest.mark.unit
def test_get_plugin_registry_skips_memory_runtime_when_globally_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_module = import_module("src.infrastructure.agent.plugins.registry")
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(agent_memory_runtime_mode="disabled"),
    )
    monkeypatch.setattr(
        registry_module,
        "_global_plugin_registry",
        AgentPluginRegistry(),
    )

    registry = registry_module.get_plugin_registry()
    plugin_names = {entry.plugin_name for entry in registry.list_hook_catalog()}

    assert "workspace-runtime" in plugin_names
    assert "sisyphus-runtime" in plugin_names
    assert "memory-runtime" not in plugin_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_hook_respects_priority_ordering() -> None:
    """Handlers with lower priority should execute before higher priority."""
    registry = AgentPluginRegistry()
    execution_order: list[str] = []

    async def _handler_a(payload):
        execution_order.append("a")

    async def _handler_b(payload):
        execution_order.append("b")

    async def _handler_c(payload):
        execution_order.append("c")

    # Register with explicit priorities: c(10), a(50), b(200)
    registry.register_hook("plugin-c", "test_hook", _handler_c, priority=10)
    registry.register_hook("plugin-a", "test_hook", _handler_a, priority=50)
    registry.register_hook("plugin-b", "test_hook", _handler_b, priority=200)

    await registry.notify_hook("test_hook", payload={"key": "value"})

    assert execution_order == ["c", "a", "b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_hook_default_priority_is_100() -> None:
    """Handlers registered without explicit priority should default to 100."""
    registry = AgentPluginRegistry()
    execution_order: list[str] = []

    async def _early(payload):
        execution_order.append("early")

    async def _default(payload):
        execution_order.append("default")

    async def _late(payload):
        execution_order.append("late")

    registry.register_hook("plugin-late", "test_hook", _late, priority=200)
    registry.register_hook("plugin-default", "test_hook", _default)  # default=100
    registry.register_hook("plugin-early", "test_hook", _early, priority=10)

    await registry.notify_hook("test_hook")

    assert execution_order == ["early", "default", "late"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_hook_executes_custom_script_runtime_override() -> None:
    """Custom script overrides should execute real code for matching lifecycle hooks."""
    registry = AgentPluginRegistry()

    result = await registry.apply_hook(
        "before_response",
        payload={"response_instructions": []},
        runtime_overrides=[
            {
                "plugin_name": "__custom__",
                "hook_name": "before_response",
                "hook_family": "mutating",
                "executor_kind": "script",
                "source_ref": "src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
                "entrypoint": "append_demo_response_instruction",
                "enabled": True,
                "priority": 15,
                "settings": {},
            }
        ],
    )

    assert result.payload["demo_hook_executed"] is True
    assert (
        "Demo runtime hook executed from custom script." in result.payload["response_instructions"]
    )
    assert result.diagnostics == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_hook_enforces_side_effect_family_no_payload_mutation() -> None:
    """Side-effect hooks should not mutate the dispatcher payload."""
    registry = AgentPluginRegistry()

    result = await registry.apply_hook(
        "after_subagent_complete",
        payload={"response_instructions": []},
        runtime_overrides=[
            {
                "plugin_name": "__custom__",
                "hook_name": "after_subagent_complete",
                "hook_family": "side_effect",
                "executor_kind": "script",
                "source_ref": "src/infrastructure/agent/hooks/scripts/demo_runtime_hook.py",
                "entrypoint": "append_demo_response_instruction",
                "enabled": True,
                "priority": 15,
                "settings": {},
            }
        ],
    )

    assert result.payload == {"response_instructions": []}


@pytest.mark.unit
def test_list_hook_catalog_includes_hook_family_metadata() -> None:
    """Registered hooks should retain canonical family metadata in the catalog."""
    registry = AgentPluginRegistry()

    async def _handler(payload):
        return payload

    registry.register_hook(
        "plugin-a",
        "before_response",
        _handler,
        hook_family="mutating",
        priority=42,
    )

    catalog = registry.list_hook_catalog()

    assert len(catalog) == 1
    entry = catalog[0]
    assert entry.hook_name == "before_response"
    assert entry.hook_family == "mutating"
    assert entry.default_executor_kind == "builtin"


@pytest.mark.unit
def test_list_hooks_includes_priority() -> None:
    """list_hooks() should return (priority, handler) tuples."""
    registry = AgentPluginRegistry()

    async def _handler(payload):
        pass

    registry.register_hook("plugin-a", "before_response", _handler, priority=42)

    hooks = registry.list_hooks()
    assert "before_response" in hooks
    entry = hooks["before_response"]["plugin-a"]
    assert isinstance(entry, tuple)
    assert entry[0] == 42
    assert entry[1] is _handler


@pytest.mark.unit
def test_register_hook_with_priority_via_runtime_api() -> None:
    """PluginRuntimeApi.register_hook() should forward priority to registry."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    registry = AgentPluginRegistry()
    api = PluginRuntimeApi("my-plugin", registry=registry)

    async def _handler(payload):
        pass

    api.register_hook("on_error", _handler, priority=5)

    hooks = registry.list_hooks()
    assert "on_error" in hooks
    priority, handler = hooks["on_error"]["my-plugin"]
    assert priority == 5
    assert handler is _handler


@pytest.mark.unit
def test_register_http_route_stores_route_metadata() -> None:
    """HTTP route registration should persist method, path, handler, summary, and tags."""
    registry = AgentPluginRegistry()

    async def _handler():
        return {"ok": True}

    registry.register_http_route(
        "plugin-a",
        "GET",
        "/items",
        _handler,
        summary="List items",
        tags=["items"],
    )

    routes = registry.list_http_routes()
    assert "plugin-a" in routes
    assert len(routes["plugin-a"]) == 1
    route = routes["plugin-a"][0]
    assert route.method == "GET"
    assert route.path == "/items"
    assert route.handler is _handler
    assert route.summary == "List items"
    assert route.tags == ["items"]


@pytest.mark.unit
def test_register_http_route_rejects_duplicate_method_path() -> None:
    """Duplicate (method, path) for the same plugin should raise ValueError."""
    registry = AgentPluginRegistry()

    registry.register_http_route("plugin-a", "POST", "/items", lambda: None)

    with pytest.raises(ValueError, match="HTTP route already registered"):
        registry.register_http_route("plugin-a", "POST", "/items", lambda: None)


@pytest.mark.unit
def test_register_http_route_allows_different_methods_same_path() -> None:
    """Different HTTP methods on the same path should be allowed."""
    registry = AgentPluginRegistry()

    registry.register_http_route("plugin-a", "GET", "/items", lambda: None)
    registry.register_http_route("plugin-a", "POST", "/items", lambda: None)

    routes = registry.list_http_routes()
    assert len(routes["plugin-a"]) == 2
    methods = {r.method for r in routes["plugin-a"]}
    assert methods == {"GET", "POST"}


@pytest.mark.unit
def test_register_http_route_normalizes_method_to_uppercase() -> None:
    """Method should be normalized to uppercase."""
    registry = AgentPluginRegistry()

    registry.register_http_route("plugin-a", "get", "/items", lambda: None)

    routes = registry.list_http_routes()
    assert routes["plugin-a"][0].method == "GET"


@pytest.mark.unit
def test_register_http_route_via_runtime_api() -> None:
    """PluginRuntimeApi.register_http_route() should forward to registry."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    registry = AgentPluginRegistry()
    api = PluginRuntimeApi("my-plugin", registry=registry)

    async def _handler():
        return {"ok": True}

    api.register_http_route("GET", "/status", _handler, summary="Health check")

    routes = registry.list_http_routes()
    assert "my-plugin" in routes
    assert len(routes["my-plugin"]) == 1
    route = routes["my-plugin"][0]
    assert route.plugin_name == "my-plugin"
    assert route.method == "GET"
    assert route.path == "/status"
    assert route.handler is _handler
    assert route.summary == "Health check"


@pytest.mark.unit
def test_clear_removes_http_routes() -> None:
    """clear() should remove all HTTP routes."""
    registry = AgentPluginRegistry()
    registry.register_http_route("plugin-a", "GET", "/items", lambda: None)

    registry.clear()

    assert registry.list_http_routes() == {}


@pytest.mark.unit
def test_register_cli_command_stores_command_metadata() -> None:
    """CLI command registration should persist name, handler, description, and args_schema."""
    registry = AgentPluginRegistry()

    async def _handler(payload: dict) -> str:
        return "result"

    registry.register_cli_command(
        "plugin-a",
        "my-command",
        _handler,
        description="My CLI command",
        args_schema={"type": "object", "properties": {"arg1": {"type": "string"}}},
    )

    commands = registry.list_cli_commands()
    assert "plugin-a" in commands
    assert len(commands["plugin-a"]) == 1
    cmd = commands["plugin-a"][0]
    assert cmd.plugin_name == "plugin-a"
    assert cmd.name == "my-command"
    assert cmd.handler is _handler
    assert cmd.description == "My CLI command"
    assert cmd.args_schema == {"type": "object", "properties": {"arg1": {"type": "string"}}}


@pytest.mark.unit
def test_register_cli_command_rejects_duplicate_name_per_plugin() -> None:
    """Duplicate CLI command name for same plugin should raise ValueError."""
    registry = AgentPluginRegistry()

    registry.register_cli_command("plugin-a", "cmd", lambda _: None)

    with pytest.raises(ValueError, match="CLI command already registered"):
        registry.register_cli_command("plugin-a", "cmd", lambda _: None)


@pytest.mark.unit
def test_register_cli_command_allows_same_name_different_plugins() -> None:
    """Same command name should be allowed for different plugins."""
    registry = AgentPluginRegistry()

    registry.register_cli_command("plugin-a", "cmd", lambda _: None)
    registry.register_cli_command("plugin-b", "cmd", lambda _: None)

    commands = registry.list_cli_commands()
    assert len(commands["plugin-a"]) == 1
    assert len(commands["plugin-b"]) == 1
    assert commands["plugin-a"][0].name == "cmd"
    assert commands["plugin-b"][0].name == "cmd"


@pytest.mark.unit
def test_register_cli_command_normalizes_name_to_lowercase() -> None:
    """CLI command name should be normalized to lowercase."""
    registry = AgentPluginRegistry()

    registry.register_cli_command("plugin-a", "MyCommand", lambda _: None)

    commands = registry.list_cli_commands()
    assert commands["plugin-a"][0].name == "mycommand"


@pytest.mark.unit
def test_register_cli_command_via_runtime_api() -> None:
    """PluginRuntimeApi.register_cli_command() should forward to registry."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    registry = AgentPluginRegistry()
    api = PluginRuntimeApi("my-plugin", registry=registry)

    async def _handler(payload: dict) -> str:
        return "result"

    api.register_cli_command(
        "my-cmd",
        _handler,
        description="Test command",
        args_schema={"type": "object"},
    )

    commands = registry.list_cli_commands()
    assert "my-plugin" in commands
    assert len(commands["my-plugin"]) == 1
    cmd = commands["my-plugin"][0]
    assert cmd.plugin_name == "my-plugin"
    assert cmd.name == "my-cmd"
    assert cmd.handler is _handler
    assert cmd.description == "Test command"
    assert cmd.args_schema == {"type": "object"}


@pytest.mark.unit
def test_clear_removes_cli_commands() -> None:
    """clear() should remove all CLI commands."""
    registry = AgentPluginRegistry()
    registry.register_cli_command("plugin-a", "cmd1", lambda _: None)
    registry.register_cli_command("plugin-a", "cmd2", lambda _: None)

    registry.clear()

    assert registry.list_cli_commands() == {}


@pytest.mark.unit
def test_register_lifecycle_hook_stores_handler() -> None:
    """Lifecycle hook registration should persist handler for valid events."""
    registry = AgentPluginRegistry()

    def _handler() -> None:
        pass

    registry.register_lifecycle_hook("plugin-a", "on_load", _handler)

    hooks = registry.list_lifecycle_hooks()
    assert "on_load" in hooks
    assert hooks["on_load"]["plugin-a"] is _handler


@pytest.mark.unit
def test_register_lifecycle_hook_rejects_unknown_event() -> None:
    """Unknown lifecycle event names should raise ValueError."""
    registry = AgentPluginRegistry()

    with pytest.raises(ValueError, match="Unknown lifecycle event"):
        registry.register_lifecycle_hook("plugin-a", "on_explode", lambda: None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_lifecycle_invokes_handlers() -> None:
    """Lifecycle notification should invoke registered handlers."""
    registry = AgentPluginRegistry()
    called: list[str] = []

    async def _handler() -> None:
        called.append("on_load")

    registry.register_lifecycle_hook("plugin-a", "on_load", _handler)

    diagnostics = await registry.notify_lifecycle("on_load")

    assert diagnostics == []
    assert called == ["on_load"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_lifecycle_collects_diagnostics_on_failure() -> None:
    """Failing lifecycle handlers should produce diagnostics."""
    registry = AgentPluginRegistry()

    async def _broken() -> None:
        raise RuntimeError("lifecycle-boom")

    registry.register_lifecycle_hook("plugin-a", "on_disable", _broken)

    diagnostics = await registry.notify_lifecycle("on_disable")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "lifecycle_hook_failed"
    assert "lifecycle-boom" in diagnostics[0].message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_lifecycle_filters_by_plugin_names() -> None:
    """Lifecycle notification should only invoke handlers for specified plugins."""
    registry = AgentPluginRegistry()
    called: list[str] = []

    registry.register_lifecycle_hook("plugin-a", "on_enable", lambda: called.append("a"))
    registry.register_lifecycle_hook("plugin-b", "on_enable", lambda: called.append("b"))

    await registry.notify_lifecycle("on_enable", plugin_names=["plugin-a"])

    assert called == ["a"]


@pytest.mark.unit
def test_clear_removes_lifecycle_hooks() -> None:
    """clear() should remove all lifecycle hooks."""
    registry = AgentPluginRegistry()
    registry.register_lifecycle_hook("plugin-a", "on_load", lambda: None)
    registry.register_lifecycle_hook("plugin-b", "on_unload", lambda: None)

    registry.clear()

    assert registry.list_lifecycle_hooks() == {}


@pytest.mark.unit
def test_register_lifecycle_hook_via_runtime_api() -> None:
    """PluginRuntimeApi.register_lifecycle_hook() should forward to registry."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    registry = AgentPluginRegistry()
    api = PluginRuntimeApi("my-plugin", registry=registry)

    def _handler() -> None:
        pass

    api.register_lifecycle_hook("on_load", _handler)

    hooks = registry.list_lifecycle_hooks()
    assert "on_load" in hooks
    assert hooks["on_load"]["my-plugin"] is _handler


@pytest.mark.unit
def test_plugin_sdk_lifecycle_shorthand() -> None:
    """PluginSDK on_load/on_enable/on_disable/on_unload should register hooks."""
    from src.infrastructure.agent.plugins.sdk import PluginSDK

    registry = AgentPluginRegistry()
    sdk = PluginSDK("my-plugin", registry=registry)

    handlers: dict[str, object] = {}
    for event in ("on_load", "on_enable", "on_disable", "on_unload"):
        h = lambda: None  # noqa: E731
        handlers[event] = h
        getattr(sdk, event)(h)

    hooks = registry.list_lifecycle_hooks()
    for event, h in handlers.items():
        assert event in hooks
        assert hooks[event]["my-plugin"] is h


# ---------------------------------------------------------------------------
# Phase 6: Config Schema Validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_register_config_schema_stores_schema() -> None:
    """register_config_schema should store schema retrievable via list_config_schemas."""
    registry = AgentPluginRegistry()
    schema = {"type": "object", "properties": {"key": {"type": "string"}}}
    registry.register_config_schema("my-plugin", schema)

    schemas = registry.list_config_schemas()
    assert "my-plugin" in schemas
    assert schemas["my-plugin"].schema == schema


@pytest.mark.unit
def test_validate_config_success() -> None:
    """validate_config should return empty list for valid config."""
    registry = AgentPluginRegistry()
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    registry.register_config_schema("my-plugin", schema)

    diags = registry.validate_config("my-plugin", {"name": "hello"})
    assert diags == []


@pytest.mark.unit
def test_validate_config_failure() -> None:
    """validate_config should return diagnostic for invalid config."""
    registry = AgentPluginRegistry()
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    registry.register_config_schema("bad-plugin", schema)

    diags = registry.validate_config("bad-plugin", {})
    assert len(diags) == 1
    assert diags[0].plugin_name == "bad-plugin"
    assert diags[0].code == "config_validation_failed"
    assert diags[0].level == "error"


@pytest.mark.unit
def test_validate_config_no_schema_returns_empty() -> None:
    """validate_config should return empty list when no schema is registered."""
    registry = AgentPluginRegistry()

    diags = registry.validate_config("unregistered-plugin", {"anything": True})
    assert diags == []


@pytest.mark.unit
def test_register_config_schema_overwrites_silently() -> None:
    """Registering a config schema twice should keep the latest schema."""
    registry = AgentPluginRegistry()
    schema_v1 = {"type": "object", "properties": {"a": {"type": "string"}}}
    schema_v2 = {"type": "object", "properties": {"b": {"type": "integer"}}}
    registry.register_config_schema("my-plugin", schema_v1)
    registry.register_config_schema("my-plugin", schema_v2)

    schemas = registry.list_config_schemas()
    assert schemas["my-plugin"].schema == schema_v2


@pytest.mark.unit
def test_clear_removes_config_schemas() -> None:
    """clear() should remove all registered config schemas."""
    registry = AgentPluginRegistry()
    registry.register_config_schema("p", {"type": "object"})
    assert len(registry.list_config_schemas()) == 1

    registry.clear()
    assert registry.list_config_schemas() == {}


@pytest.mark.unit
def test_register_config_schema_via_runtime_api() -> None:
    """PluginRuntimeApi.register_config_schema should delegate to registry."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    registry = AgentPluginRegistry()
    api = PluginRuntimeApi("api-plugin", registry=registry)
    schema = {"type": "object", "properties": {"x": {"type": "number"}}}
    api.register_config_schema(schema)

    schemas = registry.list_config_schemas()
    assert "api-plugin" in schemas
    assert schemas["api-plugin"].schema == schema


@pytest.mark.unit
def test_register_config_schema_via_sdk() -> None:
    """PluginSDK.register_config_schema should delegate to registry via api."""
    from src.infrastructure.agent.plugins.sdk import PluginSDK

    registry = AgentPluginRegistry()
    sdk = PluginSDK("sdk-plugin", registry=registry)
    schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
    sdk.register_config_schema(schema)

    schemas = registry.list_config_schemas()
    assert "sdk-plugin" in schemas
    assert schemas["sdk-plugin"].schema == schema
