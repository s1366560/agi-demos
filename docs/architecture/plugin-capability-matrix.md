# Platform Plugin Capability Matrix (P0 Baseline)

Acceptance baseline for the full-pluginization roadmap. It complements
`plugin-capability-inventory.md` (ownership/migration view) with a **runtime
coverage view**: each of the 21 `CapabilityKind`s across the four runtime
columns — Python backend, Rust core/sidecar, Web frontend, Desktop app.

Status legend:

- **done** — production path runs through the plugin/capability mechanism.
- **partial** — mechanism exists, but coverage or wiring is incomplete.
- **builtin** — trusted builtin implementation; replaceable only by builtin manifests.
- **kernel** — explicit non-plugin surface (see `platform-plugin-kernel.md`).
- **gap** — no mechanism yet; scheduled by the roadmap phase noted.

## Matrix

| Capability kind | Python backend | Rust core / sidecar | Web frontend | Desktop app |
| --- | --- | --- | --- | --- |
| `agent_loop` | partial: kind relaxed to builtin/signed (python-trusted only); `agent_loop_runtime.AgentLoopResolver` resolves per turn by `(provider, model)` — model > provider > auto(`supports()` priority) > builtin fallback; wiring into `SessionProcessor` remains | done: `RuntimeHarness` embedded + CLI backend (ADR-0008, `crates/core`, `adapters-cli-harness`) | n/a | done: embedded harness via sidecar local runtime |
| `system_prompt_section` | partial: runtime guidance / agent definition prompts are builtin, not yet capability rows (P2) | gap | n/a | gap |
| `tool` | done: V2 tool generations (`tool_runtime.py`) + V1 factories mirrored by `legacy_inventory_bridge.py` | done: `HotPlugRegistry` + `ToolHost` seam (`crates/plugin-host`) | n/a | done: sidecar `authorized_tool_host` consumes the same registry |
| `skill_provider` | partial: V1 skill factories + loaders; V2 mirroring via bridge; declarative skills are builtin | done: `SkillEngine` (declarative data + Rhai trigger) in `crates/plugin-host` | n/a | partial: available through plugin-host, no profile-driven skills yet |
| `subagent_provider` | partial: V1 resolver factories (mirrored); subagent runtime builtin | partial: manifest kind exists in `plugin-host` | n/a | done: sidecar `subagent_agent_tool_host` / `subagent_runtime` |
| `hook` | done: typed event bus (`events.py`) with 4 dispatch modes + legacy adaptation (`agent_events.py`) | partial: `hooks` manifest field; host hook execution server-side | n/a | partial |
| `policy` | kernel: tool pipeline, permission manager, hook security policy | partial: `tool_authority` / authorized hosts enforce policy in sidecar | n/a | done: authority metadata + authorized dispatch (desktop local mode) |
| `llm_provider` | done: V2 routed adapter providers are the only path (V2 cutover, `llm_adapters.py`, `llm_runtime.py`) | done: `adapters-http-llm` behind core ports | n/a | done: sidecar provider management + credential vault leases |
| `embedder` | partial: provider-manager backed; capability kind reserved (P1/P4) | gap | n/a | gap |
| `reranker` | partial: retrieval services builtin; capability kind reserved (P4) | gap | n/a | gap |
| `channel` | partial: V1 channel adapter factories (mirrored); connection manager builtin | partial: manifest kind exists | n/a | builtin: WS/control channels in sidecar |
| `http_route` | done(mount): builtin surface mounts from `builtin-routes.v1.json` via `route_loader.install_builtin_routes` (order/prefix preserved); `HttpRouteMountService` adds reversible plugin routes; per-row profile patching via `route:<row_id>` profile patches (I1 B6) | builtin: axum routers in server/sidecar | n/a | builtin: sidecar route modules |
| `cli_command` | partial: V1 CLI commands (mirrored) | gap | n/a | n/a |
| `ui_slot` | done(backend): `UiSlotRegistry` allowlist, builtin/signed only, sandbox enforced | n/a | partial: `pluginSlotService` consumes snapshot slots, `PluginSlotHost` sandboxed iframe + protocol landed (P3); page wiring remains | gap (P3) |
| `ui_renderer` | done(backend): slot definitions only | n/a | partial: same P3 host/protocol covers renderer slots; keyed renderers remain | gap (P3) |
| `storage` | kernel/builtin: repositories and artifact stores | partial: plugin snapshot/activation/artifact SQLite stores in sidecar | n/a | done: `plugin_snapshots.rs` durable requested/applied state |
| `graph_backend` | builtin: native graph adapter behind ports (P4 for plugin replacement) | done(adapter): `adapters-neo4j` | n/a | n/a |
| `retrieval_backend` | builtin: hybrid search / retrieval registry (P4) | gap | n/a | n/a |
| `workflow_engine` | builtin: workflow engine + background managers (P4) | partial: sidecar automation dispatcher/worker | n/a | partial: automation worker |
| `credential_source` | kernel: application credential vault; kind reserved builtin-only, never a plugin provider | kernel: sidecar `application_vault` | n/a | kernel: desktop vault + trusted session broker |
| `telemetry_exporter` | builtin: OTel/Jaeger stack (P4) | builtin: tracing | n/a | builtin |

## Cross-runtime mechanisms (P0 verified)

| Mechanism | Python backend | Rust core / sidecar | Desktop app |
| --- | --- | --- | --- |
| Manifest contract (schema v1) | `src/domain/model/plugins/manifest.py` | `crates/plugin-host/src/manifest.rs` + `snapshot.rs` | consumed via snapshot sync |
| Profile layers + whole-config patch | `src/infrastructure/plugins/profile.py` | `crates/plugin-host/src/profile_reconcile.rs` | applied by reconciler |
| Snapshot reconcile (staging + last-good + ACK/NACK) | `snapshot_reconciler.py`, `runtime_host.py` | `profile_reconcile.rs` | `platform_plugin_sync.rs` + `plugin_snapshots.rs` (SQLite last-good) |
| Registry hot-swap | generation swap + in-flight pinning (`tool_runtime.py`) | `ArcSwap` atomic swap (ADR-0006) | same registry |
| V1/V2 inventory unification | `legacy_inventory_bridge.py` (P0) | n/a | n/a |
| Composition root | done: `service_registry.py` + `configuration/service_bindings.py` (126 accessor rows); container facades resolve through the per-container registry (I1) | static wiring in app bins | static wiring |
| Config audit (`dump-config`) | `dump_config.py` + `scripts/dump_plugin_profile.py` (layer provenance, canonical JSON digest) | consumes the same canonical JSON | same |
| Bundle distribution | `bundle.py` `.mspkg` (manifest + layer rows + patches, bounded zip) (P4) | OCI artifact path retained | same |
| Profile hot-reload | `profile_watch.py` recompose + last-good + envelope events (P4) | `platform_plugin_sync.rs` polling reconciler | same |
| Agent loop resolution | `agent_loop_runtime.AgentLoopResolver` per-turn `(provider, model)` (P2) | `HarnessRegistry::select` (ADR-0008) | same semantics |
| Untrusted plugin runtime | not yet (P5) | `adapters-wasmtime` (server/desktop) | `adapters-wasmtime` wired in sidecar |
| Plugin artifact distribution | package archive/registry (`package_archive.py`, `package_registry.py`) | OCI artifact pull in `platform_plugin_sync.rs` | OCI artifact pull + digest verification |

## P0 exit criteria mapping

1. V1/V2 registry merge: `legacy_inventory_bridge.py` mirrors V1 tools, skills,
   hooks, channels, HTTP routes, CLI commands, and sub-agent resolvers into the
   kernel `CapabilityRegistry`; V1 facade deprecated (kept one release cycle).
2. Desktop consumes `agistack-plugin-host`: already satisfied — the sidecar
   depends on `plugin-host` + `adapters-wasmtime` and runs
   `PlatformPluginControlPlaneReconciler` against the Python control plane.
3. This matrix is the coverage baseline; P1+ phases update the status cells as
   capabilities move to **done**.

## Roadmap progress log (post-P0)

| Phase | Landed | Remaining |
| --- | --- | --- |
| P1 | Route surface mounts from `builtin-routes.v1.json` via `route_loader`; `ServiceRegistry` composition root; DI migration done (126 bindings, facades cut over I1); dump-config CLI; per-row route patching through profiles | (complete) |
| P2 | `AgentLoopResolver` per-turn `(provider, model)` seam; `agent_loop` relaxed to builtin/signed (python-trusted); requirement resolution fixed (`@plugin` pins) | Wire the resolver into `SessionProcessor` turn start; model-visible⇒logged shared invariant tests |
| P3 | Web slot consumption: `pluginSlotService` + `pluginSlotProtocol` + `PluginSlotHost` (sandboxed iframe, builtin modules, `ui.*` permissions) | Page wiring (settings/conversation/tool-card slots), desktop renderer, keyed renderer registry |
| P4 | `.mspkg` bundle format + install CLI; profile templates (server/desktop/headless); `profile_watch` hot-reload with last-good | Marketplace → bundle install wiring; admin UI (plugin/profile/row views) |
| P5 | (pre-existing) `adapters-wasmtime` server/desktop path | Python-side WASM host, subprocess/MCP boundaries, tenant quotas and audit |
