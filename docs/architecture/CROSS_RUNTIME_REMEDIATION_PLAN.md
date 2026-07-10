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
- Make the Rust server require `DATABASE_URL` unless explicit development mode
  is enabled. Keep legacy unauthenticated `/v1/*` routes disabled by default.

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
  persistence, and browser rendering. Keep Agent/Ray/LLM/Sandbox scenarios as a
  separately provisioned full-product gate.
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
- GitHub Actions workflow YAML parsed successfully.

The basic backend-dependent Playwright gate is complete. The remaining
full-product E2E suite still requires deterministic Ray worker, LLM, graph
mutation, and sandbox fixtures; the basic auth/project gate is not represented
as complete Agent-runtime parity.
