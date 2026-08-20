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
| `agent_loop` | done: kind relaxed to builtin/signed (python-trusted only); `agent_loop_runtime.AgentLoopResolver` resolves per turn by `(provider, model)` — model > provider > auto(`supports()` priority) > builtin fallback; wired into `SessionProcessor` per turn (I2/R1); live WS verification records `loop_id`/`plugin_id`/`scope=builtin` in the execution summary; `system_prompt_section` consumed from the registry with builtin fallback | done: `RuntimeHarness` embedded + CLI backend (ADR-0008, `crates/core`, `adapters-cli-harness`) | n/a | done: embedded harness via sidecar local runtime |
| `system_prompt_section` | partial: builtin native-tool-protocol row registered; processor merges registry sections with builtin fallback (I2); agent-definition prompts remain builtin | gap | n/a | gap |
| `tool` | done: V2 tool generations (`tool_runtime.py`) + V1 factories mirrored by `legacy_inventory_bridge.py` | done: `HotPlugRegistry` + `ToolHost` seam (`crates/plugin-host`) | n/a | done: sidecar `authorized_tool_host` consumes the same registry |
| `skill_provider` | partial: V1 skill factories + loaders; V2 mirroring via bridge; declarative skills are builtin | done: `SkillEngine` (declarative data + Rhai trigger) in `crates/plugin-host` | n/a | partial: available through plugin-host, no profile-driven skills yet |
| `subagent_provider` | partial: V1 resolver factories (mirrored); subagent runtime builtin | partial: manifest kind exists in `plugin-host` | n/a | done: sidecar `subagent_agent_tool_host` / `subagent_runtime` |
| `hook` | done: typed event bus (`events.py`) with 4 dispatch modes + legacy adaptation (`agent_events.py`) | partial: `hooks` manifest field; host hook execution server-side | n/a | partial |
| `policy` | kernel: tool pipeline, permission manager, hook security policy | partial: `tool_authority` / authorized hosts enforce policy in sidecar | n/a | done: authority metadata + authorized dispatch (desktop local mode) |
| `llm_provider` | done: V2 routed adapter providers are the only path (V2 cutover, `llm_adapters.py`, `llm_runtime.py`) | done: `adapters-http-llm` behind core ports | n/a | done: sidecar provider management + credential vault leases |
| `embedder` | done(server): builtin manifest row + registry-first `BackendCapabilityResolver`; adapter preserves the existing LiteLLM embedder facade as the builtin fallback (R3a) | gap | n/a | gap |
| `reranker` | done(server): builtin manifest row + registry-first `BackendCapabilityResolver`; hybrid-search reranking uses the capability seam with the existing LiteLLM facade as fallback (R3a) | gap | n/a | gap |
| `channel` | partial: V1 channel adapter factories (mirrored); connection manager builtin | partial: manifest kind exists | n/a | builtin: WS/control channels in sidecar |
| `http_route` | done(mount): builtin surface mounts from `builtin-routes.v1.json` via `route_loader.install_builtin_routes` (order/prefix preserved); `HttpRouteMountService` adds reversible plugin routes; per-row profile patching via `route:<row_id>` profile patches (I1 B6) | builtin: axum routers in server/sidecar | n/a | builtin: sidecar route modules |
| `cli_command` | partial: V1 CLI commands (mirrored) | gap | n/a | n/a |
| `ui_slot` | done(backend): `UiSlotRegistry` allowlist, builtin/signed only, sandbox enforced | n/a | done: shared `@agistack/plugin-slots` contract + keyed renderer registry + outlets mounted in settings/sidebar/toolbar/chat/canvas (I3) | partial: contract aligned (local mirror + contract field); conversation_renderer mounts below the chat panel via SignedUiModuleBoundary (I3) |
| `ui_renderer` | done(backend): slot definitions only | n/a | done: keyed renderer registry (contract `tool-result:<tool>`) drives tool result cards; sandbox host fallback (I3) | partial: tool_result_renderer preview + signed boundary in settings (I3) |
| `storage` | kernel/builtin: repositories and artifact stores | partial: plugin snapshot/activation/artifact SQLite stores in sidecar | n/a | done: `plugin_snapshots.rs` durable requested/applied state |
| `graph_backend` | done(server): builtin manifest row + registry-resolved backend builders layered after the native graph composition; builtin fallback and `project_id` scoping are preserved (R3b) | done(adapter): `adapters-neo4j` | n/a | n/a |
| `retrieval_backend` | done(server): builtin manifest row + registry-resolved backend builders layered after the hybrid-search/retrieval composition (R3b) | gap | n/a | n/a |
| `workflow_engine` | done(server): builtin manifest row + registry-first resolution; the previous builtin-absent `None` behavior remains unchanged when no row is active (R3c) | partial: sidecar automation dispatcher/worker | n/a | partial: automation worker |
| `credential_source` | kernel: application credential vault; kind reserved builtin-only, never a plugin provider | kernel: sidecar `application_vault` | n/a | kernel: desktop vault + trusted session broker |
| `telemetry_exporter` | done(server): builtin manifest row + registry-first resolution with a total noop builtin fallback (R3c) | builtin: tracing | n/a | builtin |

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
| Untrusted plugin runtime | done (I5): `wasm_host.py` (wasmtime, fuel + digest + fresh store per call) + `subprocess_host.py` (JSON-RPC, timeout kill, crash isolation); untrusted manifests restricted to tool capabilities at the trust gate; `plugin_audit` events + `ResourceQuotaEnforcer` wired | `adapters-wasmtime` (server/desktop) | `adapters-wasmtime` wired in sidecar |
| MCP stdio process boundary | done (R2): shared `process_boundary.py` adds trust tiers, allowlist-scrubbed child environments, bounded stdout, untrusted timeout-kill, crash isolation, and `plugin_audit` lifecycle events without changing MCP JSON-RPC framing | n/a | desktop-local MCP servers inherit the Python boundary when launched through the backend |
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
| P2 | `AgentLoopResolver` per-turn `(provider, model)` seam; `agent_loop` relaxed to builtin/signed (python-trusted); requirement resolution fixed (`@plugin` pins); resolver wired into the live `SessionProcessor` path (I2/R1); live WS chat verified builtin resolution and `agent_loop={loop_id, plugin_id, scope}` in the execution summary; `system_prompt_section` seam (I2); canonical native Electron launch, provider connection/model discovery, and outbound chat request verified | Native provider-backed completion remains externally blocked: the available Kimi and GLM credentials returned quota/credit failures (403/429), so no successful native reply is claimed |
| P3 | Web slot consumption: `pluginSlotService` + `pluginSlotProtocol` + `PluginSlotHost`; shared `@agistack/plugin-slots` package; keyed renderer registry; page outlets (settings/nav/composer/conversation/canvas); tool-result contract renderers; desktop contract alignment + conversation mount (I3) | (complete) |
| P4 | `.mspkg` bundle format + install CLI; profile templates (server/desktop/headless); `profile_watch` hot-reload with last-good; approved marketplace installs land in the active profile via `install_bundle_into_profile` (I4); PluginHub control-plane admin (cutover gate + profile + row views) (I4); embedder/reranker/graph/retrieval/workflow/telemetry backend capability seams and builtin manifests landed (R3a–R3c) | (complete) |
| P5 | Python WASM host + subprocess boundary + trust-gate tool-only shape for untrusted + quota/audit wiring (I5); MCP stdio server spawns hardened through the shared trust/environment/output/timeout/audit boundary (R2) | (complete) |
