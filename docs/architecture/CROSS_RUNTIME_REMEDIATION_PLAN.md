# Cross-runtime remediation plan

Last updated: 2026-07-10

This plan records the Desktop, Rust, Python, Web, and architecture-document
audit remediation. It separates release-blocking boundary repairs from
long-running product parity work. Passing a platform build proves that an
artifact ships; it does not prove feature parity with the Python/Web product.

## Target architecture

| Surface | Current product responsibility | Near-term contract |
| --- | --- | --- |
| Python/FastAPI | Production system of record and complete Agent runtime | Authenticated, tenant/project-scoped reference behavior |
| Web | Complete production management and Agent UI | Reference client for HITL, replay, and recovery contracts |
| Rust server | Strangler control/read/write slices over the shared schema | Fail closed outside explicit development mode; no public demo mutations |
| Desktop | Authenticated cloud subset plus an explicit local host runtime | No anonymous loopback capabilities and no simulated backend controls |
| Portable Rust core | Runtime-independent memory and ReAct foundations | Shared narrow core, not a claim of full product parity |

## Phase 0 — release-blocking boundaries

Status: implemented and covered by regression tests in the current working tree.

- Require authentication and project membership before Python terminal REST or
  WebSocket code can reach a Docker shell.
- Authenticate security and tunnel WebSockets; restrict tunnel diagnostics to
  administrators and return aggregate data only.
- Give each Desktop local-runtime launch a high-entropy capability token. Check
  it before HTTP handlers and WebSocket upgrades, use an exact origin allowlist,
  and never return the LLM provider secret in runtime status.
- Constrain Desktop local file operations to canonical workspace paths, reject
  symlink escapes, bound terminal queues, and terminate timed-out children.
- Require a per-container capability for Sandbox MCP WebSockets, pass it only
  through the authorization header, recover it from Docker metadata after an
  API restart, and bind MCP, desktop, and terminal host ports to loopback.
  Legacy containers without a capability fail closed until rebuilt.
- Make the Rust server require `DATABASE_URL` unless explicit development mode
  is enabled. Keep legacy unauthenticated `/v1/*` routes disabled by default.
- Require AutoBroker's semantic tier/category verdict to come from the
  structured `route_request` agent tool-call. If that judgment is unavailable,
  leave semantic filters unset and preserve only objective capabilities already
  present in the request; never substitute a keyword or default-category guess.

Exit criteria:

1. Anonymous and wrongly scoped requests fail before a shell, PTY, tool host, or
   security pipeline is invoked.
2. Positive tests prove an authorized project member and an authenticated local
   Desktop client retain supported behavior.
3. Exploit regression tests, formatters, linters, and owning-package tests pass.

## Phase 1 — protocol and product truth

Status: implemented for the supported Desktop contracts.

- Remove duplicate Python task detail/cancel routes so runtime routing and
  OpenAPI describe the same canonical handler.
- Disable or accurately label Desktop pause/resume/stop/review controls until a
  real backend command contract exists.
- Complete Desktop HITL submission and WebSocket reconnect, heartbeat,
  acknowledgement, cursor replay, and conversation-scoped subscription logic.
- Ensure Desktop local conversations can execute more than one turn and that
  terminal session identifiers are scoped and single-use.
- Render server-authorized, stateless A2UI buttons in Desktop only when the
  persisted surface and `allowed_actions` contract agree exactly. Reject
  dynamic contexts, unsafe object keys, orphan surfaces, and unsupported forms.
- Honor the selected Sandbox profile image and desktop capability in create,
  rebuild, API-restart recovery, and cross-process sync paths. Do not publish or
  report a desktop endpoint when the profile disables it.
- Accept that same stateless A2UI subset on the Rust `:8088` HITL boundary only
  after an exact persisted allow-list match. Seal the database recovery payload
  and Redis response independently with the Python-compatible AES-256-GCM
  envelope; fail before claiming the request when encryption is unavailable.
- Distinguish Local Memory from server Project Memory in labels and docs.

Exit criteria:

1. UI state cannot claim a backend action that was not acknowledged.
2. Disconnect/reconnect tests prove no silent permanent loss of subscription.
3. Clarification, decision, permission, and environment-variable requests have
   an actionable Desktop response path or are explicitly unsupported.

## Phase 2 — continuous verification and documentation

Status: the first continuous-verification increment is implemented.

- Exclude test modules from Python coverage, enforce the verified 72.80%
  production baseline in CI, and ratchet the gate to the repository's 80%
  target as the remaining production branches receive tests.
- Run Web typecheck, unit tests, and production build on every pull request.
- Run a backend-independent Playwright browser smoke gate without requiring LLM
  credentials.
- Run a real backend-dependent Playwright gate against migrated pgvector
  PostgreSQL, Redis, Neo4j, FastAPI bootstrap authentication, tenant/project
  persistence, and browser rendering.
- Run deterministic local and Ray Agent/LLM gates against a fresh migrated
  database, the real authenticated Agent WebSocket, Redis event streaming,
  persisted conversation history, and an OpenAI-compatible fixture with no
  external key. The fixture must exercise AutoBroker's real structured
  `route_request` tool-call rather than a fallback. Ray mode must be explicit
  and the API log must prove the router and ProjectActor path.
- Run a deterministic authenticated FastAPI-to-Neo4j mutation gate that proves
  episode ingestion, entity extraction, embedding, relationship extraction,
  project-scoped detail/list queries, hybrid search, and graph visualization.
  Keep the full Sandbox image scenario as a separately provisioned release
  gate.
- Exclude local secrets, Git metadata, caches, reports, runtime volumes, and
  language build outputs from root Docker build contexts.
- Build a locked, non-root MCP-only Sandbox contract image in CI and exercise
  authentication, tenant isolation, loopback publication, Docker metadata,
  write/read/bash tools, workspace escape rejection, and container teardown.
  Keep the full Desktop/Terminal production image as a separate release gate.
- Build that full image from Ubuntu 24.04 as a non-root process, expose only the
  profile-declared services, and launch two instances on separate owned bridge
  networks. The release fixture must prove MCP capability authentication,
  query-token rejection, complete toolchains, KasmVNC and ttyd readiness,
  restart recovery, loopback publication, and cross-network authentication
  denial. Docker-published ports remain routable across bridge networks, so
  network metadata alone is not treated as a tenant security boundary.
- Run Rust Postgres/Redis tests against real CI services and run Desktop source
  checks before bundling.
- Make this document and `ARCHITECTURE.md` the cross-runtime authority; keep the
  `agi-stack` execution plan as detailed Rust migration evidence.

## Follow-on parity program

These are architectural migrations, not safe hot fixes, and remain planned
after the release blockers above:

- Persist Desktop workspace, conversation, message, timeline, and checkpoint
  state transactionally instead of mixing SQLite checkpoints with process-local
  maps.
- Extend Desktop A2UI beyond stateless buttons only after persisted form state,
  dynamic value resolution, safe context projection, and component-path
  validation have cross-client parity tests. Rust continues to reject dynamic
  A2UI context and `env_var` responses until those contracts are implemented.
- Migrate the complete Agent worker, HITL orchestration, event replay, plugin
  hooks, graph/reflexion, and sandbox lifecycle to Rust only behind per-capability
  parity tests and explicit strangler gates.
- Replace placeholder local tool implementations with truthful capability names
  and contracts; do not treat a matching tool name as semantic parity.
- Decide whether Local Memory synchronizes with Project Memory. Until that
  product decision is implemented, keep the stores visibly separate.
- Enforce plugin trust metadata so untrusted and MCP-supplied code only executes
  in the documented WASM boundary.

## Verification ledger

Verified on 2026-07-10:

- Python security/router regression suites: 50 targeted tests passed; Ruff,
  Mypy, Pyright, i18n, and diff checks passed.
- Python: a clean full unit rerun passed 12,851 tests. The original 81.41%
  coverage figure incorrectly counted test code; the production-only baseline
  increased from 72.48% to 72.87%, with a non-regression gate of 72.80% that
  omits `src/tests` and an explicit follow-on target of 80%.
- Python coverage/security increments: Markdown memory path confinement,
  heartbeat token handling, pool recommendations, pricing validation, and LLM
  cache behavior have dedicated regression suites; the touched cache and
  pricing modules reached 100% coverage and Markdown memory reached 88%.
- Python static typing: repository-wide Mypy now passes all 1,446 source files,
  and Pyright passes with zero errors. The repair also aligned the graph-store
  port signature, kept tenant-scoped gene reviews fail closed, and corrected
  validated Cypher identifiers that had previously evaluated to `None`.
- Rust server: 531 tests passed and Clippy passed with warnings denied; the
  production-mode binary fails closed when `DATABASE_URL` is absent, while
  explicit `AGISTACK_DEV_MODE=1` starts the in-memory development runtime.
- Rust/Python HITL parity: stateless A2UI responses require an exact persisted
  `(source_component_id, action_name)` pair, reject dynamic context, seal DB and
  Redis payloads with independent nonces, and never publish plaintext response
  data. Rust's Python-compatible AES-GCM vectors passed 2/2 and the Python HITL
  consumer/persistence regression suite passed 45/45.
- Desktop Rust: 14 tests passed; local tools: 9 tests passed; workspace Rust
  tests, formatting, checks, and clippy passed.
- Desktop UI: 14 protocol/authentication/A2UI tests passed and the production
  build passed.
- Web: typecheck and production build passed; 341 files / 3,555 unit tests and
  Playwright smoke tests 2/2 passed.
- Backend E2E: migrations, bootstrap verification, FastAPI, and the dedicated
  Playwright auth/project smoke suite passed 2/2 against real local PostgreSQL,
  Redis, and Neo4j services.
- Agent/LLM E2E: a fresh isolated database was initialized and migrated, then
  the deterministic OpenAI-compatible fixture drove the real authenticated
  Agent WebSocket through completion and persisted-history verification. The
  fixture also returned the real `route_request` tool-call: the API recorded an
  audited `source=llm` AutoBroker verdict and did not enter a semantic heuristic
  fallback. The broker/fake-provider/pooled-client/Agent-First regression suite
  passed 34/34; Ruff and Mypy passed, and Pyright reported zero errors.
- Ray Agent E2E: a host-local Ray 2.53 head, detached HITL router, and
  ProjectActor completed the same authenticated WebSocket and history contract
  with `AGENT_RUNTIME_MODE=ray`; the API log proved the non-fallback Ray path.
  The gate disables Ray's automatic `uv run` working-directory upload and uses
  a direct same-host GCS address to avoid packaging the repository into CI.
- Graph E2E: an isolated migrated PostgreSQL database plus disposable Redis and
  Neo4j services rejected anonymous episode creation, then the deterministic
  OpenAI-compatible fixture drove entity extraction and 1,536-dimensional
  embeddings. The authenticated API wrote two typed entities, two `MENTIONS`
  edges, and one `FOUNDED` fact, and read them back through episode detail,
  entity list, relationship, hybrid-search, and graph-visualization endpoints.
  The live run also exposed and fixed Neo4j temporal response serialization and
  a malformed project-scoped `EXISTS` Cypher clause.
- Sandbox MCP security: direct unauthenticated WebSocket access closed with
  code 4001 while the capability-authenticated `ping` contract succeeded.
  Server tests passed 57/57 (plus one skipped) and Sandbox adapter tests passed
  106/106 across create, rebuild, recovery, sync, profile, and connection paths.
- Docker build context: the root exclusion contract is regression-tested and
  prevents local environment files, credentials, VCS state, caches, reports,
  runtime data, and compiled artifacts from entering `COPY . .` layers.
- Sandbox lifecycle E2E: the 786 KB filtered build context produced a locked,
  non-root MCP-only image; a real FastAPI project lifecycle rejected anonymous
  and cross-tenant creation, blocked direct unauthenticated MCP with code 4001,
  completed write/read/bash calls, rejected an out-of-workspace write, verified
  loopback-only ports and no Docker socket, and removed the container cleanly.
- Full Sandbox release gate: workflow, metadata validator, MCP exploit probes,
  restart checks, and two-network isolation fixture are implemented. Its unit
  contract passed 11/11, the current Sandbox regression selection passed
  234/234, and the nested server suite passed 320 tests with 104 legacy
  integration scenarios skipped. The production image now uses one Python
  environment and one Playwright browser installation instead of duplicating
  both globally and in a virtual environment; shared writable pip caching is
  disabled by default.
- The optimized Ubuntu 24.04 production image built successfully on local
  linux/arm64 as
  `sha256:1e499e9ece02f5b5dea60f332b4a22918177a504cfc025509200d270de53e349`.
  A fresh full-runtime execution proved non-root metadata, authenticated MCP,
  authenticated KasmVNC and ttyd, restart recovery, capability non-disclosure,
  and denial of unauthenticated and wrong-capability requests from a second
  sandbox network. The dynamic desktop/terminal manager paths use the same
  fail-closed runtime credential contract.
- GitHub Actions workflow YAML parsed successfully.

The backend-dependent Playwright, deterministic local/Ray Agent, graph mutation,
and MCP-only Sandbox gates are complete. The full Desktop/Terminal fixture now
passes against a fresh local linux/arm64 production image. The scheduled
linux/amd64 execution and a rendered RFB/terminal browser path remain the final
evidence gaps; local arm64 success is not represented as cross-architecture or
browser-rendering parity.
