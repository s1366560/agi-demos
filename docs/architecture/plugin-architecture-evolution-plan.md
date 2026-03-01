# Plugin Architecture Evolution Plan

Reference: OpenClaw Plugin Architecture (`openclaw-plugin-architecture.md`)
Target: MemStack Agent Plugin System

## Gap Analysis: OpenClaw vs MemStack

| # | OpenClaw Capability | MemStack Status | MemStack Method |
|---|-------------------|-----------------|-----------------|
| 1 | Tools | EXISTS | `register_tool_factory()` / `build_tools()` / `build_plugin_tool_infos()` |
| 2 | Hooks | EXISTS (basic) | `register_hook()` / `notify_hook()` (named hooks, no taxonomy) |
| 3 | Channels | EXISTS | `register_channel_type()` / `register_channel_adapter_factory()` |
| 4 | Commands | EXISTS | `register_command()` / `execute_command()` |
| 5 | HTTP Routes | MISSING | No HTTP route registration from plugins |
| 6 | Gateway Methods | MISSING | No gateway method registration |
| 7 | CLI Commands | MISSING | No CLI command registration from plugins |
| 8 | Services | EXISTS | `register_service()` / `get_service()` |
| 9 | Providers | EXISTS | `register_provider()` / `get_provider()` |
| - | **Skills** | **MISSING** | No `register_skill_factory()` or `build_skills()` |

### MemStack-Specific Gaps

1. **Skill Registration** (CRITICAL): Rich skill system exists (544-line `Skill` entity, `SkillSource` enum, filesystem loader, skill loader tool) but plugins cannot register skills. Manifest has `skills: tuple[str, ...]` metadata but no runtime registration/build API.
2. **Hook Taxonomy**: OpenClaw defines 20+ specific hook names; MemStack has generic hooks.
3. **Hook Priority**: OpenClaw supports numeric priority; MemStack has none.
4. **Plugin Config Schema Validation**: OpenClaw validates configs against JSON Schema; MemStack does not.
5. **Plugin SDK**: OpenClaw has dedicated SDK; MemStack has `PluginRuntimeApi` but no full SDK.

## Phased Implementation Roadmap

### Phase 1: Plugin Skill Registration and Discovery (HIGH PRIORITY)

**Why first**: The skill system is mature (L2 layer) but completely disconnected from the plugin system. Tools already work through plugins -- skills should too.

**Files to modify**:
- `src/domain/model/agent/skill/skill_source.py` -- Add `PLUGIN = "plugin"`
- `src/infrastructure/agent/plugins/registry.py` -- Add `PluginSkillFactory`, `PluginSkillBuildContext`, `register_skill_factory()`, `build_skills()`, `list_skill_factories()`
- `src/infrastructure/agent/plugins/runtime_api.py` -- Add `register_skill_factory()`
- `src/infrastructure/agent/state/agent_worker_state.py` -- Wire plugin skills into `get_or_create_skills()`

**New file**:
- `src/infrastructure/agent/tools/plugin_skills.py` -- Bridge module (analogous to `plugin_tools.py`)

**Tests**:
- `src/tests/unit/infrastructure/agent/plugins/test_plugin_registry.py` -- Add skill factory tests

**Pattern**: Replicate `build_tools()` / `_add_plugin_tools()` / `build_plugin_tool_infos()` pattern.

### Phase 2: Hook Taxonomy and Priority System

**Why second**: Hooks exist but are generic. Adding a taxonomy of well-known hook names and priority ordering brings MemStack's hook system to parity with OpenClaw.

**Scope**:
- Define well-known hook names (e.g., `before_tool_selection`, `after_tool_execution`, `before_response`, `on_error`)
- Add numeric `priority` field to hook registration
- Sort hook handlers by priority before invocation

**Files to modify**:
- `registry.py` -- Add priority to `_hook_handlers` storage and sorted invocation
- `runtime_api.py` -- Add `priority` parameter to `register_hook()`

### Phase 3: HTTP Handler Registration

**Why third**: Enables plugins to expose custom API endpoints, necessary for webhook receivers, OAuth callbacks, and plugin-specific APIs.

**Scope**:
- Add `register_http_handler()` / `register_http_route()` to registry
- Create FastAPI router that mounts plugin-registered routes
- Namespace plugin routes under `/api/v1/plugins/{plugin_name}/`

**Files to modify**:
- `registry.py` -- Add HTTP handler storage and retrieval
- `runtime_api.py` -- Add `register_http_handler()` / `register_http_route()`
- New router module for mounting plugin HTTP routes

### Phase 4: CLI Command Registration

**Why fourth**: Enables plugins to extend the CLI interface for operational tasks.

**Scope**:
- Add `register_cli()` to registry
- Create CLI adapter that discovers and mounts plugin CLI commands

### Phase 5: Plugin SDK Enrichment

**Why fifth**: Once all registration primitives are in place, wrap them in a developer-friendly SDK.

**Scope**:
- Create `PluginSDK` class that bundles `PluginRuntimeApi` with convenience methods
- Add plugin lifecycle hooks (`on_load`, `on_enable`, `on_disable`, `on_unload`)
- Create plugin template generator

### Phase 6: Plugin Config Schema Validation

**Why last**: Non-blocking for functionality but improves plugin reliability.

**Scope**:
- Add JSON Schema validation for plugin config at load time
- Report validation errors as diagnostics
- Support `config_schema` in plugin manifest

## Dependencies Between Phases

```
Phase 1 (Skills) ─────> Phase 5 (SDK)
Phase 2 (Hooks) ──────> Phase 5 (SDK)
Phase 3 (HTTP) ───────> Phase 5 (SDK)
Phase 4 (CLI) ────────> Phase 5 (SDK)
Phase 5 (SDK) ────────> Phase 6 (Config Validation)
```

Phases 1-4 are independent and can be parallelized. Phase 5 depends on all of 1-4. Phase 6 depends on 5.

## Implementation Notes

### Phase 1 Design Details

**Type Aliases**:
```python
PluginSkillFactory = Callable[
    ["PluginSkillBuildContext"],
    list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
]
```

**Context Dataclass**:
```python
@dataclass(frozen=True)
class PluginSkillBuildContext:
    tenant_id: str
    project_id: str
    agent_mode: str
```

**Key difference from tools**: Tool factories return `dict[str, Any]` (name->impl mapping). Skill factories return `list[dict[str, Any]]` (list of skill definition dicts) because skills are richer objects with triggers, scopes, and templates.

**Integration point**: `get_or_create_skills()` in `agent_worker_state.py` (line 2354) is where filesystem skills are loaded and cached. Plugin skills merge here using a `_add_plugin_skills()` helper that mirrors `_add_plugin_tools()`.
