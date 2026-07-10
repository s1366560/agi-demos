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

Status: implemented for the supported Desktop contracts in the current working tree.

- Remove duplicate Python task detail/cancel routes so runtime routing and
  OpenAPI describe the same canonical handler.
- Disable or accurately label Desktop pause/resume/stop/review controls until a
  real backend command contract exists.
- Complete Desktop HITL submission and WebSocket reconnect, heartbeat,
  acknowledgement, cursor replay, and conversation-scoped subscription logic.
- Ensure Desktop local conversations can execute more than one turn and that
  terminal session identifiers are scoped and single-use.
- Distinguish Local Memory from server Project Memory in labels and docs.

Exit criteria:

1. UI state cannot claim a backend action that was not acknowledged.
2. Disconnect/reconnect tests prove no silent permanent loss of subscription.
3. Clarification, decision, permission, and environment-variable requests have
   an actionable Desktop response path or are explicitly unsupported.

## Phase 2 — continuous verification and documentation

Status: implemented in CI and documentation in the current working tree.

- Exclude test modules from Python coverage, enforce the current 72% production
  baseline in CI, and ratchet the gate to the repository's 80% target as the
  remaining production branches receive tests.
- Run Web typecheck, unit tests, and production build on every pull request.
- Run a backend-independent Playwright browser smoke gate without requiring LLM
  credentials; keep full service E2E as a separately provisioned gate.
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
- Python: a clean full unit rerun passed 12,687 tests. The original 81.41%
  coverage figure incorrectly counted test code; the production-only baseline
  is 72.48%, with a non-regression gate of 72% that omits `src/tests` and an
  explicit follow-on target of 80%.
- Rust server: 526 tests passed; the production-mode binary fails closed when
  `DATABASE_URL` is absent, while explicit `AGISTACK_DEV_MODE=1` starts the
  in-memory development runtime.
- Desktop Rust: 14 tests passed; local tools: 9 tests passed; workspace Rust
  tests, formatting, checks, and clippy passed.
- Desktop UI: 9 protocol/authentication tests passed and the production build
  passed.
- Web: typecheck and production build passed; 341 files / 3,555 unit tests and
  Playwright smoke tests 2/2 passed.
- GitHub Actions workflow YAML parsed successfully.

The backend-dependent Playwright suite still requires a separately provisioned
database, users, Ray worker, sandbox runtime, and deterministic LLM fixture. It
is not represented as a completed parity gate by the browser-only smoke suite.
