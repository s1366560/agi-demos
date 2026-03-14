# Plugin & Tool Subsystem Refactoring Proposal

**Date**: 2026-03-14
**Status**: Proposed
**Scope**: Unification of plugin systems, tool registries, and custom tool integration
**Supersedes**: Consolidates findings from `plugin-architecture-evolution-plan.md`, `PLUGIN_TOOL_PIPELINE_FIX.md`, and `TOOL_SYSTEM_IMPROVEMENT_PROPOSAL.md`

---

## Executive Summary

The MemStack plugin and tool subsystem has grown organically into a capable but structurally fragmented system. After exhaustive analysis of every file in both subsystems, we identified **6 structural problems** that produce real bugs (silent tool failures, naming inconsistencies, duplicate registries) and developer confusion (two plugin systems, three tool registration paths, unclear contracts).

This proposal presents a phased refactoring plan with concrete file-level changes. Each phase is independently shippable and backward compatible.

---

## 1. Problems Identified

### P1: Two Parallel Plugin Systems

Two independent plugin loading systems exist:

| System | Location | Discovery | Registry |
|--------|----------|-----------|----------|
| **Runtime** | `src/infrastructure/agent/plugins/` | `discovery.py` (builtin + local + entrypoint) | `AgentPluginRegistry` (16 extension types, 977 lines) |
| **Standalone** | `.memstack/plugins/plugin_loader.py` | `memstack.plugin.json` manifest scan | Own `_registered_plugins`, `_tool_factories`, `_hooks`, etc. (243 lines) |

The standalone loader (`.memstack/plugins/plugin_loader.py`) duplicates the runtime system with its own `PluginAPI` class, separate registries, and independent discovery. This creates:
- Confusion about which system actually loads plugins at runtime
- Potential double-registration if both systems discover the same plugin
- Maintenance burden of keeping two systems in sync

**Recommendation**: Absorb the standalone loader into the runtime system. The standalone loader appears to be an earlier prototype that was superseded by the full `src/infrastructure/agent/plugins/` implementation.

### P2: Dual Tool Registries

Two tool registries coexist:

| Registry | Location | Storage | Purpose |
|----------|----------|---------|---------|
| `ToolRegistry` | `src/infrastructure/agent/tools/tool_registry.py` | `_tools` (legacy `Tool` ABC) + `_tool_infos` (new `ToolInfo`) | Global singleton, dual storage |
| `AgentPluginRegistry` | `src/infrastructure/agent/plugins/registry.py` | `_tool_factories` (plugin factories) | Plugin-specific tool factories |

The `ToolRegistry` maintains two internal dicts (`_tools` for legacy class-based tools, `_tool_infos` for new `ToolInfo`-based tools) plus the `AgentPluginRegistry` has its own `_tool_factories`. Tools flow through three different paths:

```
Path 1: Built-in tools -> tool_converter.py -> ToolDefinition -> processor
Path 2: Custom tools -> CustomToolLoader -> @tool_define -> ToolInfo -> processor  
Path 3: Plugin tools -> registry.build_tools() -> raw objects -> plugin_tools.py -> ToolInfo -> processor
```

Each path has different contracts, error handling, and capabilities.

### P3: Plugin Tools Are Second-Class Citizens

Plugin tool factories return raw Python objects. The `plugin_tools.py` bridge module attempts to convert them to `ToolInfo` via `plugin_tool_to_info()`, but:
- Objects with `__call__` only (not `execute`) fail silently in `tool_converter.py`
- Parameter schema introspection is best-effort and often produces empty schemas
- Plugin name attribution is lossy (guessed from diagnostics)
- No dependency management for non-sandbox plugin tools

This was documented in detail in `PLUGIN_TOOL_PIPELINE_FIX.md` with concrete fixes. Those fixes should be implemented as part of this refactoring.

### P4: Custom Tools Disconnected from Plugin System

`.memstack/tools/*.py` files are loaded by `CustomToolLoader` (493 lines) using a snapshot-diff approach on `_TOOL_REGISTRY`. This is entirely separate from the plugin system:
- Custom tools cannot register hooks, commands, services, or lifecycle handlers
- Custom tools cannot declare dependencies in a manifest
- No enable/disable state management for custom tools
- No reload capability (restart required)

Custom tools are effectively "plugins that can only register tools." They should be a simplified interface into the plugin system, not a parallel system.

### P5: Missing Manifest for Local Plugins

The Feishu plugin in `.memstack/plugins/feishu/` has no `memstack.plugin.json` manifest. It's an 8-line shim that imports from `src/`. The `pdf-assistant` and `example-showcase` plugins correctly have manifests, but there's no enforcement.

### P6: Inconsistent Tool Naming Conventions

MCP tools use inconsistent naming:
- `MCPToolAdapter`: `mcp_{server_id}_{tool_name}` (single underscore)
- `SandboxMCPServerToolAdapter`: `mcp__{server}__{tool}` (double underscore)
- `MCPTool.full_name` (domain model): `mcp__{server}__{tool}` (double underscore)

This causes lookup failures across boundaries.

---

## 2. Refactoring Plan

### Phase 1: Absorb Standalone Plugin Loader (LOW RISK)

**Goal**: Eliminate the duplicate plugin system in `.memstack/plugins/plugin_loader.py`.

**Changes**:

| File | Action | Description |
|------|--------|-------------|
| `.memstack/plugins/plugin_loader.py` | DELETE | Remove the standalone loader entirely |
| `src/infrastructure/agent/plugins/discovery.py` | VERIFY | Confirm `LocalPluginDiscovery` already covers all discovery that `plugin_loader.py` was doing |
| Any imports of `plugin_loader` | GREP + FIX | Find and remove any references to the standalone loader |

**Verification**: After removal, run `plugin_manager(action="list")` to confirm all plugins are still discovered. Run `plugin_manager(action="enable", plugin_name="...")` and `plugin_manager(action="reload")` to confirm lifecycle still works.

**Compatibility**: The standalone loader was not wired into the agent runtime path (no imports from `src/` reference it). Removal should have zero runtime impact.

### Phase 2: Implement Plugin Tool Adapter Layer (MEDIUM RISK)

**Goal**: Make plugin tools first-class citizens by implementing the adapter layer described in `PLUGIN_TOOL_PIPELINE_FIX.md`.

This phase implements the 5 fixes from `PLUGIN_TOOL_PIPELINE_FIX.md`:

| Fix | File(s) | Description |
|-----|---------|-------------|
| Fix 1 | `src/infrastructure/agent/tools/result.py` | Add `ToolResult.error()` and `ToolResult.success()` factory methods |
| Fix 2 | NEW: `src/infrastructure/agent/plugins/plugin_tool_adapter.py` | `_adapt_plugin_tool()` + `_introspect_callable_parameters()` |
| Fix 3 | `src/infrastructure/agent/plugins/manifest.py` | Add `PluginDependencies` to manifest metadata |
| Fix 4 | `.memstack/tools/pdf_tools.py` | Fix `ToolResult(error=...)` to `ToolResult(output=..., is_error=True)` |
| Fix 5 | `src/infrastructure/agent/core/tool_converter.py` | Add `__call__` to `_resolve_execute_method` |

**New file**: `src/infrastructure/agent/plugins/plugin_tool_adapter.py`

```python
"""Adapter layer that converts raw plugin tool objects to ToolInfo.

Plugin tool factories return arbitrary objects. This module inspects
each object and wraps it as a ToolInfo that the agent pipeline can
consume. Handles:
- Objects with __call__ (e.g., PDFTool subclasses)
- Objects with execute/run methods
- ToolInfo instances (pass-through)
- Dict metadata (description + parameters + execute)
"""
```

**Key behaviors**:
- Callable resolution: checks `execute`, `ainvoke`, `_arun`, `_run`, `run`, `__call__` in order
- Parameter schema introspection: `inspect.signature()` on the callable, maps type annotations to JSON Schema types
- Return value normalization: `ToolResult` pass-through, `dict` with `status` field, `str`, all converted to `ToolResult`
- Plugin name attribution: read `_plugin_origin` attribute set by `build_tools()` in registry

**Integration point**: `_add_plugin_tools()` in `agent_worker_state.py` calls `_adapt_plugin_tool()` for each raw tool object before adding to the tools dict.

### Phase 3: Unify Tool Registry (MEDIUM RISK)

**Goal**: Single source of truth for all tool registrations.

**Current state**: `ToolRegistry` has `_tools` + `_tool_infos`, `AgentPluginRegistry` has `_tool_factories`. These are three separate storage locations.

**Target state**: `ToolRegistry` becomes the single owner of all tool registrations. Plugin tool factories still live in `AgentPluginRegistry` but their output flows through `ToolRegistry` after adaptation.

**Changes**:

| File | Action | Description |
|------|--------|-------------|
| `src/infrastructure/agent/tools/tool_registry.py` | MODIFY | Deprecate `_tools` dict (legacy `Tool` ABC). Migrate all legacy tools to `_tool_infos` via adapter. Add `register_plugin_tools(adapted_tools)` method. |
| `src/infrastructure/agent/tools/plugin_tools.py` | MODIFY | `build_plugin_tool_infos()` uses the adapter from Phase 2, returns `list[ToolInfo]`. Remove guesswork for plugin name. |
| `src/infrastructure/agent/state/agent_worker_state.py` | MODIFY | `_add_plugin_tools()` calls adapter + registers with `ToolRegistry` |

**Migration path for legacy tools**:
1. Keep `_tools` dict but mark it as `@deprecated`
2. `get_tool()` checks `_tool_infos` first, falls back to `_tools`
3. New registrations go to `_tool_infos` only
4. Gradually migrate built-in tools from class-based to `@tool_define`

### Phase 4: Custom Tools as Lightweight Plugins (LOW RISK)

**Goal**: Make `.memstack/tools/` a special case of the plugin system rather than a parallel system.

**Current state**: `CustomToolLoader` (493 lines) has its own discovery, loading, snapshot-diff capture, and sandbox mode wrapping. It's completely independent of the plugin system.

**Target state**: Custom tools are loaded as "implicit plugins" with tool-only capabilities. The `CustomToolLoader` still handles the `.memstack/tools/` scan and `@tool_define` capture, but registers tools through the plugin registry rather than directly into the tools dict.

**Changes**:

| File | Action | Description |
|------|--------|-------------|
| `src/infrastructure/agent/tools/custom_tool_loader.py` | MODIFY | After capturing `@tool_define` tools, register them via `AgentPluginRegistry.register_tool_factory()` with a synthetic plugin name `custom:{tool_name}` |
| `src/infrastructure/agent/plugins/discovery.py` | MODIFY | Add `CustomToolDiscovery` source that delegates to `CustomToolLoader` |
| `src/infrastructure/agent/plugins/registry.py` | NO CHANGE | Already supports tool factory registration |

**Benefits**:
- Custom tools appear in `plugin_manager(action="list")` output
- Custom tools get the same adapter layer as plugin tools (Phase 2)
- Future: custom tools could opt into hooks, commands, lifecycle via manifest

**Compatibility**: Existing `.memstack/tools/*.py` files continue to work with zero changes. The `@tool_define` decorator is unchanged.

### Phase 5: Enforce Plugin Manifest Requirement (LOW RISK)

**Goal**: All plugins must have a `memstack.plugin.json` manifest.

**Changes**:

| File | Action | Description |
|------|--------|-------------|
| `src/infrastructure/agent/plugins/discovery.py` | MODIFY | `LocalPluginDiscovery` emits a warning diagnostic for plugins without `memstack.plugin.json`. After a deprecation period, make it an error. |
| `src/infrastructure/agent/plugins/manifest.py` | MODIFY | Add `PluginDependencies` dataclass (from Phase 2). Add `validate_manifest()` function. |
| `.memstack/plugins/feishu/memstack.plugin.json` | CREATE | Add manifest for Feishu plugin (see Feishu migration plan) |

**Manifest validation checks**:
- `id` is present and matches directory name
- `kind` is one of: `tool`, `channel`, `provider`, `integration`
- `version` follows semver
- `name` and `description` are non-empty
- `dependencies.python` entries are valid PEP 508 requirement specifiers

### Phase 6: Standardize MCP Tool Naming (LOW RISK)

**Goal**: Single naming convention for all MCP tools.

**Standard**: Always use double underscore `mcp__{server}__{tool}` matching the domain model `MCPTool.full_name`.

**Changes**:

| File | Action | Description |
|------|--------|-------------|
| `src/infrastructure/agent/mcp/adapter.py` | MODIFY | Change `MCPToolAdapter` naming from `mcp_{server}_{tool}` to `mcp__{server}__{tool}` |
| `src/infrastructure/mcp/sandbox_tool_adapter.py` | VERIFY | Already uses `mcp__{server}__{tool}` |
| `src/domain/model/mcp/tool.py` | VERIFY | Already uses `mcp__{server}__{tool}` |
| Any code that constructs MCP tool names | GREP + FIX | Ensure consistent double underscore |

---

## 3. Dependency Graph

```
Phase 1 (Absorb standalone loader) ──── independent
Phase 2 (Plugin tool adapter) ────────── independent
Phase 3 (Unify registry) ────────────── depends on Phase 2
Phase 4 (Custom tools as plugins) ────── depends on Phase 3
Phase 5 (Enforce manifest) ───────────── independent (but ideally after Phase 2 for PluginDependencies)
Phase 6 (MCP naming) ────────────────── independent
```

Recommended execution order: 1, 2, 5, 6 (parallel) -> 3 -> 4

---

## 4. Effort Estimates

| Phase | Effort | Risk | Files Changed | Files Created | Files Deleted |
|-------|--------|------|---------------|---------------|---------------|
| 1. Absorb standalone loader | 0.5 day | Low | 0-2 | 0 | 1 |
| 2. Plugin tool adapter | 2-3 days | Medium | 4-5 | 1 | 0 |
| 3. Unify registry | 2-3 days | Medium | 3-4 | 0 | 0 |
| 4. Custom tools as plugins | 1-2 days | Low | 2-3 | 0 | 0 |
| 5. Enforce manifest | 1 day | Low | 2-3 | 1 | 0 |
| 6. MCP naming | 0.5 day | Low | 1-3 | 0 | 0 |
| **Total** | **7-10 days** | | | | |

---

## 5. Relationship to Existing Proposals

### `plugin-architecture-evolution-plan.md` (6 phases)

| Their Phase | Status | This Proposal |
|-------------|--------|---------------|
| Phase 1: Plugin Skill Registration | **DONE** (skill factories already exist in registry.py, plugin_skills.py bridge exists) | No action needed |
| Phase 2: Hook Taxonomy + Priority | **DONE** (18 well-known hooks, priority field exists) | No action needed |
| Phase 3: HTTP Route Registration | **DONE** (register_http_route exists in registry + runtime_api) | No action needed |
| Phase 4: CLI Command Registration | **DONE** (register_cli_command exists) | No action needed |
| Phase 5: Plugin SDK | **DONE** (sdk.py exists with lifecycle shorthands) | No action needed |
| Phase 6: Config Schema Validation | **DONE** (register_config_schema exists) | No action needed |

The evolution plan's 6 phases have all been implemented since that doc was written. This proposal addresses the **structural issues** that remain after those capabilities were added.

### `PLUGIN_TOOL_PIPELINE_FIX.md` (5 fixes)

This proposal's Phase 2 implements all 5 fixes from that document. The fixes are sound and should be implemented as-is.

### `TOOL_SYSTEM_IMPROVEMENT_PROPOSAL.md` (12 areas)

This is a broader, longer-term vision document. This proposal focuses on the **plugin/tool integration** subset:
- Sections 1-2 (Tool definition + unified execution) -- longer term, not in this proposal's scope
- Section 6 (ToolContext) -- longer term
- Section 10-12 (MCP unification) -- Phase 6 of this proposal covers naming; full MCP unification is longer term

---

## 6. Testing Strategy

Each phase should include:

1. **Unit tests** for new/modified functions (adapter, introspection, naming)
2. **Integration test**: plugin discovery -> tool loading -> adaptation -> execution
3. **Regression test**: existing plugins (pdf-assistant, example-showcase, feishu) still load and execute
4. **Smoke test**: `plugin_manager(action="list")` shows all expected plugins

Key test scenarios:
- Plugin tool with `__call__` only (no `execute`) is adapted correctly
- Plugin tool with empty parameter schema gets introspected parameters
- Plugin tool returning `dict` is normalized to `ToolResult`
- Plugin tool with declared dependencies gets dependency check
- Custom tool loaded via `@tool_define` appears in plugin list
- MCP tool names are consistently `mcp__{server}__{tool}`
- Removing `.memstack/plugins/plugin_loader.py` does not break plugin discovery

---

## 7. Rollback Strategy

Each phase is independently revertible:
- Phase 1: Restore `plugin_loader.py` from git
- Phase 2: Remove adapter module, revert `_add_plugin_tools` changes
- Phase 3: Revert `ToolRegistry` changes, restore dual storage
- Phase 4: Revert `CustomToolLoader` changes, restore direct registration
- Phase 5: Remove manifest validation, revert discovery changes
- Phase 6: Revert naming changes (this one is riskier if MCP tools are in use)

---

## Appendix A: Current File Inventory

### Plugin Infrastructure (`src/infrastructure/agent/plugins/`)

| File | Lines | Purpose |
|------|-------|---------|
| `manager.py` | ~400 | `PluginRuntimeManager` singleton, orchestrates discovery/loading/lifecycle |
| `discovery.py` | ~200 | Three discovery sources: builtin, local, entrypoint |
| `loader.py` | 59 | `AgentPluginLoader`, calls `plugin.setup(api)` |
| `registry.py` | 977 | `AgentPluginRegistry`, 16 extension types, thread-safe |
| `runtime_api.py` | 282 | `PluginRuntimeApi`, scoped API surface for plugins |
| `sdk.py` | 199 | `PluginSDK`, convenience wrapper with lifecycle shorthands |
| `control_plane.py` | 193 | `PluginControlPlaneService`, high-level control operations |
| `manifest.py` | 132 | `PluginManifestMetadata` parser |
| `state_store.py` | 223 | JSON-based enable/disable state persistence |
| `selection_pipeline.py` | 523 | `ToolSelectionPipeline`, 4-stage tool selection |
| `policy_context.py` | 84 | `PolicyContext` with 8 default layers |
| `reload_planner.py` | 80 | `PluginReloadPlan` dataclass |
| `plugin_skill_loader.py` | 231 | SKILL.md loader for plugin directories |
| `subagent_plugin.py` | 140 | `SubAgentPlugin` protocol |
| `__init__.py` | ~50 | Package exports |

### Tool Subsystem (`src/infrastructure/agent/tools/`)

| File | Lines | Purpose |
|------|-------|---------|
| `custom_tool_loader.py` | 493 | Scans `.memstack/tools/`, snapshot-diff on `_TOOL_REGISTRY` |
| `custom_tool_status.py` | 82 | `@tool_define` diagnostic tool for custom tool status |
| `tool_provider.py` | 199 | Factory functions for tool providers |
| `tool_registry.py` | 560 | `ToolRegistry` with dual `_tools` + `_tool_infos` storage |
| `plugin_tools.py` | 177 | Bridge: plugin factories -> ToolInfo |
| `plugin_skills.py` | 183 | Bridge: plugin skills -> Skill domain entities |
| `tool_mutation_guard.py` | 114 | Mutation detection for self-modifying tool flows |
| `plugin_manager.py` | 993 | `plugin_manager` agent tool for list/install/enable/disable/reload |

### Standalone Loader (to be removed)

| File | Lines | Purpose |
|------|-------|---------|
| `.memstack/plugins/plugin_loader.py` | 243 | Parallel plugin system with own registries |

---

## Appendix B: Extension Point Inventory

The `AgentPluginRegistry` supports 16 extension types. All are already implemented and functional:

| # | Extension Type | Registration Method | Build/Query Method |
|---|---------------|--------------------|--------------------|
| 1 | Tool factories | `register_tool_factory()` | `build_tools()` |
| 2 | Skill factories | `register_skill_factory()` | `build_skills()` |
| 3 | Channel reload hooks | `register_channel_reload_hook()` | `notify_channel_reload()` |
| 4 | Channel adapter factories | `register_channel_adapter_factory()` | `build_channel_adapter()` |
| 5 | Channel type metadata | `register_channel_type()` | `get_channel_types()` |
| 6 | Hook handlers (18 hooks) | `register_hook()` | `notify_hook()` |
| 7 | Commands | `register_command()` | `execute_command()` |
| 8 | Services | `register_service()` | `get_service()` |
| 9 | Providers | `register_provider()` | `get_provider()` |
| 10 | HTTP routes | `register_http_route()` | `get_http_routes()` |
| 11 | CLI commands | `register_cli_command()` | `get_cli_commands()` |
| 12 | Lifecycle hooks | `register_lifecycle_hook()` | `notify_lifecycle()` |
| 13 | Config schemas | `register_config_schema()` | `validate_config()` |
| 14 | Sandbox tool factories | `register_sandbox_tool_factory()` | `build_sandbox_tools()` |
| 15 | SubAgent resolver factories | `register_subagent_resolver_factory()` | `build_subagent_resolvers()` |
| 16 | Sandbox dependencies | (declared via `runtime_api`) | (read at build time) |
