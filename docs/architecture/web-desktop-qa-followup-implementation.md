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

I4.11 constructs Cron scheduler resources and configuration inside each V2 candidate,
with activation after publication and stop/drain ownership retained by that generation.
Shared PostgreSQL and engine infrastructure remain host resources. Candidate failure,
replacement, cancellation and stale PostgreSQL epochs have focused coverage. The server
suite passed 634 tests; three generation PostgreSQL tests and three adapter PostgreSQL
tests passed. Clippy retained 17 existing warnings. The three worker artifacts sharing
the changed source were refreshed with the formal generator, whose check passed.
Cloud ownership cutover and native scheduling acceptance remain pending.

I3.6 adds generation-admitted native pull through the trusted cloud session broker.
The sidecar obtains the durable cursor and remote page itself, verifies current auth
and project access, and commits the page while holding the unchanged session identity.
Renderer requests carry scope only. Session clear/rotation/expiry, permission denial,
malformed pages and timeout/retry have regression coverage. The complete sidecar suite
passed 677 tests; Clippy added no knowledge-sync diagnostics. Conflict resolution,
cloud writer enrollment and native bidirectional acceptance remain pending.

I3.7 fences asynchronous processing-status writes by the captured project, memory
revision and task identity. These updates cannot insert a missing row or overwrite
portable content, and legacy payloads without a valid source revision skip Memory
writeback. Producers persist source identity before starting the workflow. Production
startup now loads the same complete manifest list used by bundle construction.
Derived-state and PostgreSQL regressions passed 91 tests; HTTP regressions passed 25;
production startup/bundle passed nine after formal artifact regeneration. Mypy and
Ruff passed; Pyright reported zero errors. Same-task attempt fencing and complete
portable-writer synchronization remain follow-up work.

I0.4 fixes native Automation editor state loss during periodic capability refresh.
The renderer generation host now memoizes using the generation state's actual fields,
so an unchanged generation preserves its route registry and mounted editor. A new
regression first failed on registry identity, then passed with generation replacement
and disable invalidation; eight focused lifecycle tests passed. Full Desktop observed
4257 passes, two binary-gated skips and two stale parity-artifact failures pending
regeneration. After source freeze, native QA retained the draft across refreshes and
successfully created a one-shot local task scheduled for 2026-09-07 16:52 +08:00.
The app exited before that trigger; recovery acceptance is still in progress.

Native Automation recovery acceptance on 2026-09-07 used the canonical Electron launch
and the existing isolated QA profile. The one-shot 16:52 +08:00 task survived app exit.
Restart produced exactly one skipped schedule history row with
`local_automation_app_was_not_running`, and no automatic execution. The first manual
catch-up exposed a form defect: the default reuse mode had no conversation binding and
failed with `local_automation_reuse_conversation_required`. After editing to fresh
conversation mode, one explicit manual run succeeded in 3237 ms. Read-only inspection
after app exit verified the persisted assistant message and complete event both contain
`NATIVE_AUTOMATION_RECOVERY_20260907_OK`, with the same tenant/project/workspace.
Evidence: `/tmp/memstack-qa-20260907/native-automation-recovery.txt` and
`/tmp/memstack-qa-20260907/native-automation-timeline.json`. Default session configuration,
run-result navigation and live history refresh remain product follow-ups; this result
does not close cloud scheduling acceptance.

I3.8 adds an online CAS primitive sharing the sync transaction, object revision,
journal, tombstone and successful receipt path. Online stale/deleted writes roll back
with a conflict error and do not create offline conflicts or failed receipts. Online
and offline request identities remain distinct. Review uncovered that write receipt
replay checked membership but not current object-write permission; both paths now
revalidate that permission before replay. Viewer downgrades and revoked edit shares
are rejected, while authorized delete replay still uses the retained tombstone author.
Seventy sync regressions passed, including nine new PostgreSQL tests; Mypy, Pyright,
Ruff, format and diff checks passed. Consumers and enrollment behavior are unchanged
in this batch. Reverting this primitive before consumer integration preserves the
existing database schema and sync data.

I4.12 aligns new Desktop automation drafts with the local API's fresh-conversation
default; editing an existing reuse job preserves its selected mode. A rendered browser
regression first failed on the default and then passed, including preservation of the
existing bound-session mode. TypeScript passed. Canonical native QA then created
`QA Native Scheduled 20260907` without changing the default conversation mode. Its
17:15 +08:00 scheduled trigger succeeded in 4350 ms, and the persisted assistant reply
was `NATIVE_AUTOMATION_SCHEDULE_20260907_OK` with a successful complete event. Evidence:
`/tmp/memstack-qa-20260907/native-automation-scheduled.txt` and
`/tmp/memstack-qa-20260907/native-automation-scheduled-timeline.json`. The earlier recovery
answer was also visible in the native conversation after restart, with Kimi selected.
This default-only change has no migration; reverting it leaves saved jobs unchanged.
Explicit reuse-session selection and richer run-detail navigation remain follow-ups.

I3.9 adds schema 6 local pull-conflict resolution with explicit local/remote/merged/
keep-both choices, three revision guards, exact conflict-set CAS, immutable archives,
idempotency and real pending outbox entries. Prepared or cloud-conflicted pushes
remain guarded. Both sides survive resolution; no cloud receipt or cursor is invented.
Device tests passed 49/49 and the complete sidecar suite passed 681/681. Core/device
strict Clippy passed; sidecar retains its existing 11 binary/12 test lint failures,
with no new knowledge diagnostics. Cloud tombstone restoration and push-conflict
orchestration remain incomplete. Downgrade requires the pre-migration backup;
older schema readers must reject schema 6 rather than alter its tables.

I2.4 adds authenticated native knowledge scope discovery and the renderer local list
projection. Discovery uses the admitted sidecar generation and workspace revision,
does not open storage, and remains readable while the release capability is closed.
Actual knowledge operations remain closed. Local pages expose has-more with no
invented total; cloud numbered pagination is retained. Cross-project/generation
responses, invalid pagination and aborted stale results are rejected. Twenty-five
focused renderer tests and TypeScript passed. Evidence logs:
`/tmp/knowledge-resolution-device-final.log`, `/tmp/knowledge-resolution-native-final.log`,
`/tmp/local-memories-renderer-focused.log`. This is protocol and component acceptance;
enabled native knowledge CRUD/sync acceptance remains outstanding.

I3.10 routes enrolled HTTP create through the shared online CAS command under the
same Project lock used by bootstrap. Explicit client key/revision are mandatory;
unsupported fields are rejected. Unenrolled authorization and fields are preserved.
Memory, journal, receipt and a dedicated pending projection task commit atomically.
Processing is explicitly deferred until a revision-fenced worker is composed;
legacy automatic/manual recovery cannot dispatch this task type. Forty-three tests
passed, including 17 real PostgreSQL HTTP cases; Ruff, Mypy and Pyright passed.
HTTP PATCH/delete and other portable writers remain incomplete. This batch has no
migration and sync enrollment stays closed; rollback must preserve accepted tasks
and receipts and cannot enable legacy writers for an enrolled project.

I4.13 introduces generation-local Cloud Cron readiness with actual model/checkpoint
composition provenance and loop-start acknowledgement. Missing HITL/permission/
sealed-environment/scoped-tools/mutation dependencies explicitly block startup.
Publication or a runtime handle alone never means running; stop, cancelled drain
and panic revoke readiness. The complete server suite passed 643 tests, with Clippy
successful and 17 existing warnings. Formal plugin artifacts were regenerated for
the shared worker implementation and memory services. Production Cron remains
blocked; Python retirement and ownership transfer have not occurred. Rollback must
keep both scheduler production gates closed. Logs: `/tmp/online-http-authority-final.log`
and `/tmp/memstack-cron-readiness-server-full.log`.

The subsequent Desktop full run observed 4260 passes, two skips and one failure:
the revision-bound parity artifact still audits the older knowledge page source.
This is an outstanding artifact refresh, not a full-suite pass. Source batches will
be frozen before the next formal parity regeneration and exact-commit validation.

I3.11 restores immutable prepared push requests even when a later pull conflict
exists, while new requests remain blocked. Restart retries preserve the original
request/change ID/sequence and later local edits. Fifty Device knowledge tests,
five native push/session tests and scoped strict Clippy passed. Cloud conflict
refresh now adds observed_current without changing the historical current snapshot;
resolution replays revalidate current write permission before returning a receipt.
Twenty-eight sync repository tests passed, including viewer downgrade and edit-share
revocation. No schema or release gate changed. Rollback must retain all prepared
requests; it may reintroduce the retry deadlock but must never rewrite those requests.
Logs: `/tmp/knowledge-prepared-retry-tests.log` and
`/tmp/knowledge-conflict-refresh-green.log`.

I4.14 adds PostgreSQL atomic HITL admission for already accepted automation runs.
The transaction rereads the persisted non-secret answer, locks run/job/operation/
HITL/checkpoint, CAS-updates the original checkpoint JSON and queues the run with a
new runtime revision. Ten real PostgreSQL tests and 52 adapter tests passed, plus
strict Clippy. No migration or production wiring changed. This primitive is not yet
the production recovery path, and does not claim that generic checkpoint writes are
fenced. Permission answers resume conversation only and do not mint tool authority;
sealed environment answers remain excluded. Rollback leaves the existing schema
unchanged and production Cron blocked. Evidence:
`/tmp/memstack-cron-hitl-admission-live.log`.

I4.15 aligns local fresh conversation selection with the Cloud executor: saved job
bindings apply only in reuse mode, while explicit run bindings still support recovery.
Manual fresh runs no longer send the job's stale conversation ID as an override.
Retry after conversation insertion but before run-history persistence reuses the
same generated run conversation after tenant/project/workspace checks. Two different
runs still create distinct conversations. Thirty-two sidecar automation regressions,
13 renderer model tests and TypeScript passed. No migration or capability change;
rollback preserves all saved conversations and run records. Native end-to-end
acceptance of reuse selection remains pending the editor's conversation picker.
Evidence: `/tmp/automation-conversation-sidecar-tests.log` and
`/tmp/automation-conversation-model-tests.log`.

I3.12 connects enrolled HTTP PATCH/delete to the shared command boundary. PATCH
stores the original partial request before materializing a snapshot; same-key replay
after later edits/deletion returns the original response, including retained SQL
fields outside the portable journal. Current write permission is checked on replay.
Project locks serialize bootstrap and online writes; disabled behavior is preserved.
Delete atomically removes shares/chunks and writes its tombstone plus deferred
projection task. The final 142-test run includes 25 new PostgreSQL HTTP tests;
Mypy, Pyright, Ruff, formatting and diff checks passed. No migration was added.
Rollback must keep enrollment closed and preserve receipts/tasks; it cannot restore
legacy writes on already enrolled projects. MemoryService/tools/use-cases and old
reprocess/derived consumers still need closure before sync is exposed. Evidence:
`/tmp/online-mutations-final.log`.

I4.16 wires dedicated run-lease persistence into the Cloud ReAct executor and makes
HITL resume use atomic admission. Checkpoint and HITL access now verifies the
persisted run revision, owner/token, current expiry, deadline, scope and actor;
post-write checks roll back writes delayed beyond expiry. Waiting-human transitions
use the same gate. Shared engine checkpoint fallback and non-atomic queue_resume
are removed from this path. Real PostgreSQL tests passed (7 persistence, 10 admission),
including independent-pool stale-worker races; Server 644, Core 63 and PG library
52 tests passed. PG strict Clippy passed; Server Clippy retains 17 existing warnings.
No migration/readiness/owner switch changed. This protects workers using the new
ports; retirement of old binaries remains a release prerequisite. Rollback must keep
Cloud Cron closed and preserve checkpoints, HITL requests and durable run records.
Evidence: `/tmp/memstack-cron-run-persistence-live.log` and
`/tmp/memstack-cron-run-server-full.log`.

I4.18 adds an explicit workspace conversation picker for reuse mode. The route
binding publishes detached exact-tenant/project choices; fresh inputs omit saved
conversation IDs and existing unloaded bindings are preserved for authority recheck.
New reuse jobs cannot submit without a selection. Twenty-two model/binding tests,
two browser form tests and TypeScript passed. Desktop full run observed 4265 passed,
2 skipped and one revision-bound entry test blocked by the uncommitted App.tsx;
that test is rerun after this commit rather than weakening the integrity check.
Canonical native launch verified create (paused), manual execution with Kimi,
matching conversation/workspace IDs, the real answer NATIVE_AUTOMATION_REUSE_20260907_OK,
and both replies visible in the same conversation after full application restart.
The QA job remains paused. No migration or capability gate changed; rollback keeps
persisted bindings and run history. Evidence: `/tmp/automation-picker-model-tests.log`,
`/tmp/automation-picker-browser-tests.log`, `/tmp/automation-picker-desktop-full.log`,
`/tmp/memstack-qa-20260907/native-automation-reuse-persistence.json`, and
`/tmp/memstack-qa-20260907/native-automation-reuse-after-restart.txt`.

I3.13 adds SQLite knowledge schema 7 with a separate immutable cloud-resolution
journal and stable resolution IDs. Verified receipts preserve the original mutation
and handle no-sequence/null keep-current responses. Concurrent local edits or newer
remote versions preserve cloud success and require explicit local reconciliation;
no automatic semantic choice is made. Applied receipts can recover through the
server journal; unknown/network outcomes remain retryable. Active views exclude
resolved/superseded records without deleting history. Schema upgrade uses the
existing backup path and fails closed on missing required tables/views. Device 68
and native knowledge 31 tests passed, with strict Core/Device Clippy. Transport and
UI are not wired; tombstone-baseline preparation remains a subsequent batch.
Rollback keeps sync closed and retains the schema-7 database/backup; an older binary
must not open newer schema data. Evidence: `/tmp/knowledge-cloud-resolution-device-all.log`,
`/tmp/knowledge-cloud-resolution-sidecar.log`, `/tmp/knowledge-cloud-resolution-clippy-all.log`.

Post-commit I4.18 entry validation remains blocked by the parity audit revision
7da7f53a differing from the newly committed App.tsx. Formal matrix regeneration and
agent review are pending source freeze; the full Desktop gate is not yet green.

I4.17 connects ordinary HITL resume to the production PostgreSQL driver. Each scope
admits persisted clarification/decision answers before runtime claim and projection;
permission/env remain excluded, with filtering before the candidate limit. Three
real PostgreSQL driver tests passed (pause, answer, driver replacement, final
projection, candidate fairness, and failure before claim), plus 17 persistence/
admission regressions and one legacy HITL integration in a fresh temporary DB.
Server 647 tests passed; Clippy retained 17 existing warnings. All readiness and owner
switches remain closed. Rollback leaves accepted records intact and must keep Cloud
Cron closed. This is a real database/stub model integration, not real provider or
legacy-scheduler cutover acceptance. Evidence: `/tmp/memstack-cron-driver-live.log`,
`/tmp/memstack-cron-driver-server-full.log`, `/tmp/memstack-cron-driver-pg-regression.log`,
`/tmp/memstack-cron-driver-legacy-pg.log`.

I4.19 fixes the native observation that completed run history coexisted with a
"never run" job summary. Local list/detail now project the latest finished run
within tenant/project/job scope, while pending runs retain the previous completed
summary. Stored jobs, revisions and immutable mutation receipts are unchanged.
The new real-ledger regression failed on the missing timestamp, then passed with
all 33 local automation tests; it also checks latest status, list/detail agreement,
receipt replay and exclusion of foreign-tenant rows. No migration/capability change.
Native visual recheck is pending the next canonical rebuild. Evidence:
`/tmp/automation-last-run-red.log` and `/tmp/automation-last-run-tests.log`.

I3.14 fences legacy MemoryService, tool, use-case and both SQL repository writers
before graph or SQL mutations. A transaction-held project lock excludes sync
enrollment while permitting graph-session foreign-key checks; enrolled projects
require structured sync write context and missing enrollment fences fail closed.
Explicit project and tenant mismatch and invalid update tenant metadata are rejected
before side effects. Real PostgreSQL concurrency and scope cases plus legacy unit/
integration regressions passed (136 total); Ruff, mypy and diff checks passed.
No migration or capability gate changed. Historical missing tenant metadata retains
legacy behavior; reprocess/derived writers and Rust portable writers remain pending.
Rollback must keep sync enrollment closed and preserve journals and user content.

I4.20 rejects expired local operation leases even before a replacement worker
claims the operation. Renewal, settlement (including waiting-human), and retry
require current expiry strictly after the clock; the clock is sampled after the
connection/transaction lock. The exact expiry boundary regression first failed on
renewal and now passes with all 34 automation tests. Existing heartbeat extension,
takeover, timeout, recovery and result projection tests remain green. No migration
or capability changes; rejected workers leave run and receipt state untouched.
Rollback must pause local automation before reverting this fencing guard. Evidence:
`/tmp/automation-expired-lease-red.log`, `/tmp/automation-expired-lease-all-tests.log`.
