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

I2.2 adds durable actor-scoped mutation receipts and scoped change cursor/detail reads.
Equal requests replay the original receipt even after later edits/deletion; conflicting
payloads fail. All content/change/receipt writes share one transaction. Core/Device
90 tests and strict Clippy passed. Schema v1 to v2 is an additive transactional migration;
the authority lifecycle must still implement pre-upgrade backup and verification before
opening production data. Processing and synchronization consumers remain pending.

I0 full-suite audit correction: the prior 16095-node baseline corresponds to `src/tests/unit`,
as confirmed by current collection of 16102 nodes after seven added admission tests.
The entire `src/tests` tree collects 16667 nodes. An attempted full-tree run failed eight
member contract tests without generation initialization and was interrupted at ACP after
259.67 seconds (49 passed). ACP passed alone and with preceding e2e/telemetry tests (50/50).
This is not a full Backend pass; both scope and interrupted execution remain explicit.

I4.1 adds per-job serialization to local operation claims. A running or waiting-human
run blocks another claim for the same tenant/project/job; unrelated jobs remain eligible.
The regression failed before the change and passed afterward, including release after
terminal completion and retention during HITL. All 26 automation tests passed. The full
sidecar strict Clippy check reports pre-existing warnings outside this patch; it is not
recorded as passing. Overlapping scheduled-fire history and missed-fire policy remain
pending and this batch does not enable cloud execution.

A unit-tree run was interrupted with 3745 passed, 43 failed and 27 setup errors after
reading an in-progress Desktop artifact whose generated manifest had not yet been rebuilt.
This run is diagnostic only. Subsequent full checks must use frozen generated artifacts.

I0.2 initializes the real plugin generation in member contract/integration fixtures and
republishes the negative-auth fixture before issuing the request, since each publication
captures its dependency overrides. All 15 member tests have passing focused evidence
(14 passed in the first run; the corrected authentication test then passed). No production
authentication or route behavior changed. Revert only affects test coverage setup.

I4.2 records overlapping scheduled fires as terminal `skipped` history with
`local_automation_previous_run_active`, without creating an executable operation.
Cursor advancement and the history record share the existing immediate transaction.
Queued, running and waiting-human predecessors block scheduled admission; a later fire
can run after the predecessor reaches terminal state. The new regression failed before
the change; all 27 automation tests then passed. Desktop recognizes/localizes `skipped`;
its model regression passed in the ongoing Desktop batch verification. No schema change.

I2.3 adds cloud memory pagination through the operation lease, HTTP projection, vault/main
broker, controller and page controls. Defaults remain page 1 / size 50; request and response
page metadata must agree, scope/cancellation checks remain enforced, and shrinking totals
allow navigation back to a valid page. Final focused tests: 68 passed, including the
concurrent-deletion correction. A prior full Desktop snapshot had 4252 passed, one failed,
zero skipped; the sole failure required committed source bytes to match HEAD. That full
snapshot predates the final two-line pagination correction, so it is not final acceptance.
Native Electron pagination QA remains pending.

I1.2 adds explicit reviewed-module artifact refresh to the protocol generator. It validates
all declared repository source languages and paths, refuses unselected drift and signed
artifact changes, and never writes in check mode. Only the reviewed memories module digest
was refreshed, followed by generated catalogs/bootstrap. Seventeen toolchain tests, Ruff
and generator check passed. Generated metadata is not a substitute for runtime acceptance.

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

I4.3 captures the worker activation time and records older scheduled fires as terminal
`skipped` with `local_automation_app_was_not_running`. Reconciliation remains bounded
by the dispatch batch, advances each occurrence atomically and creates no execution
operation for missed fires. Previously accepted operations remain recoverable. The
restart regression first reached the executor incorrectly; after the fix, three missed
fires remain in history without execution and an exact startup-boundary fire is eligible.
All 28 automation tests passed. Missed-count presentation and an explicit catch-up action
remain pending; this is not the complete local automation release.

I4.4 makes local cron projection use civil-time candidates and explicit timezone
resolution. Nonexistent times are skipped; ambiguous times use the first instant only,
and candidates must move forward in UTC. Regressions exposed the library's gap snapping
and backward candidate in a repeated hour before the fix. All 30 automation tests passed,
including gap, fold and ordinary timezone transitions. Cloud projection still needs the
same policy before the joint release gate can close. No storage schema changed.

I4.5 extracts PostgreSQL runtime claim selection and its private row decoder into
`cron_runtime_claim.rs` without changing queries or behavior. This keeps the existing
repository below the file-size limit before the serialization fix. All 52 adapter unit
tests and strict library Clippy passed. Reverting this structural batch has no database
or runtime behavior effect; live PostgreSQL concurrency checks follow separately.
