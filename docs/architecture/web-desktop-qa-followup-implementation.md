# Web / Desktop QA follow-up implementation

Approved baseline: `e9ae3a1d3`, 2026-09-07. Evidence source:
[QA report](web-desktop-functional-qa-2026-09-07.md).

## Product and release constraints

- Offline means an independent local runtime. Keep existing Provider/API configuration;
  do not add model installation or management.
- Release local knowledge only together with bidirectional project knowledge sync.
  Retain both conflicting versions for explicit user resolution.
- Release cloud and local automation together. Local execution requires the application
  to remain running; a complete exit pauses scheduling. Missed fires are visible and
  require an explicit one-time catch-up action.
- Preserve Cordis V2 authority, generation, scope, operation leases and vault boundaries.
- Work in reversible batches. A passing component test does not close an iteration.

## Iteration ledger

| Iteration | Work | Status | Release gate |
| --- | --- | --- | --- |
| I0 | Cron admission, coherent test evidence, credential recovery | In progress | No orphan admission; same-revision full checks |
| I1 | Shared contracts, snapshot isolation, entrypoint extraction | In progress | Cross-process positive and negative contracts |
| I2 | Scoped local knowledge, CRUD/CAS, jobs, cloud operations | In progress | Scope, revision, durability; release with I3 |
| I3 | Local extraction/retrieval, entities/community, bidirectional sync | Pending | Offline runtime and conflict/recovery acceptance |
| I4 | Single cloud scheduler authority and local execution parity | Pending | Real runs and recovery in all three client modes |
| I5 | Graph navigation, processing/sync diagnostics, populated governance QA | Pending | Actionable diagnosis and recovery |
| I6 | Identity, external integrations and signed/platform releases | Pending | Per-platform and per-integration evidence |

## Batch I0.1: command admission

The Python route advertised `run_now.allowed=false` but accepted V2 durable commands.
The route now consults the same capability builder used by discovery before either
legacy execution or durable admission. Membership and target checks remain first.
Unavailable commands return HTTP 503 with the capability reason code and do not queue
or commit. This batch deliberately leaves the production execution capability disabled;
I4 must supply a generation-owned, fenced and ready execution authority before enabling it.

Regression evidence: the initial admission tests produced three failures; all three
command shapes crossed the boundary. The first corrected run passed 25 Cron unit tests.
The additional HTTP contract regression passed with the existing router tests (13/13).
Across these focused runs, 26 unique Cron unit tests passed. Generation-backed API and
real PostgreSQL command/projection integration tests also passed (2/2). Ruff checks,
formatting, staged credential scan and GitNexus scope detection passed. These focused
results do not replace I0's outstanding full-suite evidence gate.

Rollback: revert the batch commit only if command admission is independently disabled.
Reverting the guard alone restores the original orphan-command risk. No data migration
or accepted-task deletion is part of this batch.

## Outstanding implementation requirements

### Implemented foundations, not feature release

- I1.1 validates compound capability supporting sources against runtime state.
  Cloud sidecar/Electron bridges remain valid; offline/native cross-runtime sources
  are rejected. TypeScript compilation and 42 related tests passed, including
  production generation settlement/drain tests. Global decoding stays fail-closed.
- I2.1 adds a strict scoped memory port and SQLite knowledge tables, CAS revisions,
  tombstones, stable pagination and atomic processing changes. Legacy unattributed
  rows remain outside the new authority. Core/Device 85 tests and strict Clippy
  passed, including concurrent CAS and transactional fault injection. Queue consumers,
  knowledge authority, indexes and sync are still pending; no local feature is enabled.

Both batches are additive or restrictive and need no live data migration. Reverting
the storage adapter does not delete its versioned tables. Reverting the source check
restores acceptance of invalid compound declarations and is not a safe security rollback.

### Remaining work

- Knowledge: tenant/project-scoped reads and deletes, CAS writes, atomic processing
  outbox, index recovery, per-action availability and cloud pagination/mutations.
- Sync: explicit project association, stable IDs, revisions, change IDs, cursor,
  receipts, tombstones and object-level conflict resolution. Rebuild indexes locally.
  Pause sync on revoked access; do not promise offline revocation of downloaded copies.
- Automation: stop and drain legacy schedules before fenced owner takeover; reject
  stale workers, deduplicate fires, serialize each job, skip overlapping schedules,
  and retain manual recovery of missed fires. Preserve HITL recovery and accepted work.
- Contracts: isolate only independently scoped capability failures; global identity,
  generation and protocol failures remain fail-closed. Preserve operation drain.
- Release: current-commit Backend, Web, Desktop and Rust suites; native Electron QA
  launched with `make -C agi-stack run-desktop`; migration/recovery and security negatives.
  External sends and production operations require their specific authorized test target.

The original 66-capability QA matrix remains unchanged until new end-to-end evidence
exists. No pending feature is considered delivered by this implementation ledger.
