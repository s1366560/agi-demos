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
| I3 | Local extraction/retrieval, entities/community, bidirectional sync | In progress | Offline runtime and conflict/recovery acceptance |
| I4 | Single cloud scheduler authority and local execution parity | In progress | Real runs and recovery in all three client modes |
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

I2.4 adds the real knowledge plugin definition to the production sidecar loader, a typed
generation-leased service, and two RPCs behind the existing native admission middleware.
Default bootstrap remains disabled and the release contract permits only `closed`. Internal
integration profiles exercise CRUD through the same Loader/publication/lease path; this
is foundation validation, not a production local knowledge success claim. Independent
SQLite activation verifies integrity and backs up pre-upgrade WAL data before migration.
Create author identity is checked at the typed service; updates cannot replace authors.

The first full sidecar run exposed missing executable catalog probes for the new routes.
After adding real closed-state negative probes, the full suite passed 657/657, with no
ignored tests. Storage/receipt focused integration passed 9/9; production catalog tests
passed 7/7. Generator check and contract completeness passed. Strict sidecar Clippy remains
blocked by existing diagnostics outside this batch. Disabling/reverting the definition
retains the independent database and receipts; never delete the knowledge directory as
part of a code rollback. The first product release still requires I3 sync and native QA.

I4.6 serializes cloud runtime claims by locking each job alongside its run and excluding
other running/waiting-human runs. A fresh query under that job lock also closes the
selection-snapshot race and prevents two candidates in the same batch from starting.
Two real PostgreSQL regressions failed before the change and passed afterward: batch
selection retains unrelated-job progress; concurrent workers claim only one run, recover
the same expired run, reject its stale lease, hold serialization during HITL, and release
it after terminal completion. Tests use private schemas in an isolated QA database.
Strict adapter Clippy passed for all targets. This does not enable cloud command readiness
or prove scheduler cutover; reverting it requires stopping parallel runtime consumers.

I1.3 moves search contract decoding and shared availability construction out of the large
workbench capability client while preserving its exports and function bodies. TypeScript
compilation and 60 focused workbench/contract/snapshot tests passed; AST comparison found
all 61 original top-level function bodies unchanged. The complete Desktop snapshot ran
4254 tests: 4250 passed, two failed and two skipped. The failures are the stale formal
parity audit for the committed cloud pagination policy and a Run Review fixture's fixed
profile entry count (436, now 437). Neither is ignored; final full Desktop/native gates
remain pending after formal inventory regeneration and fixture correction. This extraction
can be reverted without a protocol, authority or data migration.

I4.7 makes scheduled cloud overlap admission atomic under the existing fenced cursor/job
lock: queued/running/waiting-human predecessors produce terminal skipped history, no
execution operation, and an advanced cursor. The result explicitly has no operation ID
for a skip. A real PostgreSQL regression first produced queued history incorrectly, then
passed for all three predecessor states, terminal release and cursor replay. Five server
coordinator tests and strict all-target adapter Clippy passed. The broader Server suite
reported 612 passed / 1 failed: its live conversation-session fixture still references the
retired `workspace_tasks` table. That existing V1 dependency remains an I0 follow-up, not
a passing full-server result. Rollback must keep overlap admission disabled or retain the
serialization guard; existing skipped history is retained and needs no schema migration.

I3.1 adds schema v3 durable replica identity, UUIDv5 change IDs, explicit scope-to-remote
association and local-origin outbox rows in the content transaction. Proven scoped v2
changes are backfilled; unattributed legacy memories stay excluded. The real closed
knowledge authority exposes association/status/outbox queries, explicitly reporting
remote authorization as unverified and transport as not started. No remote revision is
inferred from a local version. The lifecycle shares the adapter's schema version and
backs up v1/v2 before upgrading. Core/device strict Clippy, 13 storage tests, 659 full
sidecar tests, generator check and contract completeness passed. Push receipts, pull
cursors, conflict application and transport remain pending. Rollback must preserve the
v3 database and replica ID; older binaries reject a newer schema instead of rewriting it.

I1.4 verifies existing independent-failure isolation: search HTTP 503 or malformed JSON
closes search only while a valid task capability retains its revision/actions; an
unclassified aggregate rejection still rejects the whole snapshot. The production
settlement logic already satisfies those regressions and is unchanged. Run Review now
checks entry uniqueness and required module structure rather than a catalog-size magic
number. TypeScript and 70 focused tests passed. Full Desktop: 4253 passed, one stale
parity audit failure, two binary-gated skips (4256 total). Formal parity refresh and real
binary/native acceptance remain open. Revert affects structure tests/whitespace only.

I3.2 adds cloud memory sync domain/application contracts, a request-scoped transaction
repository and an unmounted router factory. Five additive metadata tables hold ordered
changes, actor-scoped receipts, tombstones and conflict snapshots while active content
stays in memories. Project row locks serialize sequence allocation and commit; CAS and
explicit resolution preserve both conflicting versions, with no automatic merge. The
existing signed INTEGER version bounds remote revisions to 2**31-1.

All 21 focused tests passed (8 repository, 6 HTTP, 7 real PostgreSQL), along with Ruff,
mypy and pyright. The autogenerated migration a931fc278146 was exercised through
upgrade/downgrade/upgrade in isolated schemas of a dedicated QA database. The repository's
historical empty Alembic baseline assumes pre-existing tables, so a clean database cannot
run the old full chain; the test dependency bootstrap was itself autogenerated and applied
through Alembic. No production database migration was applied. Before release, existing
content bootstrap, all legacy writers, indexing and generation-owned mounting must join
this protocol. Disable the route to roll back; retain all metadata tables/receipts and
conflict snapshots once any real synchronization data exists.

I4.8 shares civil-time cron projection through `agistack-automation-schedule`, used by
both the cloud server and native sidecar. Cloud regression tests first reproduced spring
02:30 snapping to 03:00 and a fall-fold result preceding the observation instant. Both
runtimes now skip missing civil times and use only the first instant of a repeated time,
while preserving stagger offsets and strictly future cursors. Cloud schedule tests: 22
passed; local automation tests: 30 passed; shared crate strict Clippy passed. No new
external dependency version was introduced. Native execution and cloud readiness gates
remain outstanding.

I4.9 projects each local job's actual next-fire cursor and persisted missed-trigger count
from SQLite without modifying content revisions or replay receipts. Counts are restricted
to tenant/project/job and the explicit app-closed reason. The local recovery notice explains
tray/quit behavior and reuses the existing permission-gated, idempotent Run command for a
single catch-up run. It labels the count as cumulative recorded misses, not an instantaneous
estimate of an unreconciled backlog. Local automation 30 passed; renderer model/client/notice
30 passed; renderer typecheck passed. Canonical native launch succeeded, but native Cron
navigation still closed because its capability has no authority revision. This pre-existing
protocol gap must be fixed before the notice's native acceptance is complete.

I3.3 adds a durable local push protocol. Prepared requests retain their change ID and
exact payload across retries; verified applied receipts update the remote baseline in
the same SQLite transaction as acknowledgment. Conflicts retain both snapshots and
block later pushes for that memory. The renderer cannot provide cloud URLs, credentials
or receipts: native transport verifies the trusted session, cloud actor and project.
Session epoch checks fence logout, credential rotation and clear/restore of the same
token; final receipt commit shares the broker's short synchronous lock. Invalid or
expired sessions leave the outbox unacknowledged. No lock spans network I/O.

Full sidecar tests: 669 passed. Knowledge HTTP tests cover session changes during
authentication, project lookup, mutation and conflict retrieval; storage and broker
tests cover replay, malformed receipts and identity fencing. Strict Core/device Clippy
and generated artifact checks passed; sidecar Clippy retains existing failures. Cloud
route enrollment/mounting, pull, manual conflict resolution and native bidirectional
acceptance remain pending. Rollback disables the new push entry point and retains the
SQLite outbox, receipts and remote baselines.

I3.4 adds explicit, currently unmounted cloud project enrollment. Bootstrap locks the
project and enrollment fence, journals the existing content snapshot with its actual
initiating administrator, and enables guarded writes atomically. PostgreSQL guards
require matching revision intent and a same-root-transaction exact snapshot journal;
content, tombstone and terminal state must agree at commit. Disabled projects retain
legacy write behavior, including their existing parent foreign-key deletion policy.
Reserved tombstone IDs also reject cross-scope UPDATE-ID collisions. Parent cascades
are permitted only when the parent project is actually absent, not merely its fence.

46 focused tests passed, including 24 enrollment PostgreSQL cases for concurrent
bootstrap/writes, repeatable-read conflicts, savepoints, stale journals, deletion and
restoration, and both restrictive and cascading parent foreign keys in isolated test
schemas. Ruff and type checks passed. No production enrollment or migration is applied;
all existing content writers and indexing must migrate before enrollment is exposed.
Rollback must stop synchronization consumers before removing the guard; preserved
journals must not be advertised as a continuous cursor after unguarded writes resume.

I4.10 closes the native Cron capability protocol gap with schema 3 and the actual
request-admitted platform generation as authority revision. Strict decoders require a
positive safe integer, preserve unavailable behavior for legacy revisionless contracts,
and reject fabricated revisions on legacy schemas. Published-generation HTTP tests
cover 51, 52, the JavaScript safe maximum and overflow rejection. Run history accepts
the declared skipped status and rejects unknown statuses. Rust automation 31 passed;
Desktop focused 87 passed; production and test TypeScript checks passed. Native UI
recovery acceptance is still pending a canonical restart with this sidecar build.

I0.3 removes retired platform Workspace table reads from the Rust conversation,
event-replay and session projections. Platform repositories return membership and
scope facts; the application composes those facts with Workspace Core authorization,
including exact tenant/project, archive status and task linkage. Owner/admin status
does not bypass Workspace authorization. The Core response decoder now accepts its
actual profiles-and-task-links envelope. Retired attempt/plan compatibility fields
remain empty, matching the Python projection rather than querying retired tables.

Cross-review additionally reproduced and fixed missing Core checks on WebSocket send
and stop admission, source-workspace authorization before rebinding, and effective
workspace linkage for legacy metadata/ID-backed rows in lists and replay. 631 server
tests passed; five added PostgreSQL regressions passed without skips using temporary
platform tables and a controlled Core HTTP fixture. Existing projection PostgreSQL
tests also passed with the retired tables absent. Clippy completed with 17 existing
warnings. This verifies code/protocol closure, not a new native cloud acceptance run.

I3.5 adds trusted local pull storage with atomic cursor compare-and-swap, remote
baselines, indexing changes and retained conflict copies. Remote applies never enqueue
local-origin outbox entries. Pending local edits/deletions preserve both versions and
block new pushes for that memory while unrelated memories continue. Local revisions
remain independent from remote revisions, and complete remote metadata is retained.
When pull observes a prepared local change whose HTTP receipt was lost, it passes the
journal's immutable receipt fields through the existing strict receipt verifier inside
the page transaction; this acknowledges the original write without overwriting later
local edits. Malformed later events roll back that acknowledgment with the whole page.

Pull storage 17 tests and the existing knowledge storage 18 tests passed; strict
Core/device all-target Clippy passed. Coverage includes concurrent connections/local
edits, injected cursor-write rollback, v4-to-v5 upgrade, restart, corrupt-v5 refusal,
delete/restore, identity/scope rejection and push receipts ahead of the pull cursor.
Native pull transport, explicit conflict-resolution UI and bidirectional acceptance
remain pending. The additive schema preserves pending data and does not advertise a
renderer capability before the complete application protocol is installed.
