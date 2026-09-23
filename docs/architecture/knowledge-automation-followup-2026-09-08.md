# Knowledge and automation follow-up evidence

This supplements [the implementation ledger](web-desktop-qa-followup-implementation.md).
The source baseline for this checkpoint is `efa0a482f`. It records implementation
and test evidence, not a release approval or native acceptance result.

The later [native knowledge acceptance](native-knowledge-acceptance-2026-09-08.md)
records the completed local CRUD, real-model extraction, embedding, indexing,
retrieval and restart journey. Remaining boundaries below describe this earlier
checkpoint; cloud synchronization and deployment acceptance are still pending.

## Cloud memory commands

`6e0e836ef`, `0ce226d89`, `d1661a89b`, `3628b9b6d`, and `449379f8f`
connect the cloud editor to a typed, generation-leased command client and the
Electron vault broker. Each command binds actor, tenant, project and context
revision to the same captured authenticated session. Create, update and delete
retain their immutable idempotency key and expected revision after an unknown
response. Conflicts require an explicit latest-version review before a new write.
Authentication loss clears identity-bound state; forbidden writes preserve the
draft but disable further writes until authority refresh. A missing object does
not count as a successful mutation.

Focused scope, broker and parser regression passed 53 tests. The typed client and
lease regression passed 29 tests. Six real Node renderer/main-to-HTTP-to-isolated-
PostgreSQL cases passed, covering enabled and disabled command protocols,
CRUD/replay, conflict, missing records and released operations
(`/tmp/cloud-memory-lease-http.log`). These tests use the actual broker and HTTP
adapter but do not constitute a native Electron UI journey.

## Native processing and route authority

`ff26ee683` adds the schema-validated processing HTTP transport. `b6d74cac5`
connects cloud and native route contexts to their generation-owned services.
`3c34fbedc` publishes native capability observations with actor and all six native
scope fields. Processing rechecks exact allowed actions and current scope around
asynchronous boundaries. Missing observations fail closed.

`080a7ee77` adds model/workspace selection, configuration review and extraction
submission. Confirmation reloads configuration and trusted catalog inputs before
creating a command. Scope changes invalidate drafts and late responses. An unknown
write response remains unresolved until explicit recovery. The UI implementation
passed 133 focused tests and three TypeScript configurations; controlled browser
checks included provider-revision drift, lost confirmation authority, unknown
responses and failed extraction receipts.

`efa0a482f` wires the selection inputs to generation-owned Provider and Workspace
catalogs, with configuration observation before and after directory loading.
The adapter and route regression passed 14 tests, including actual generation
leases, provider revisions, project-wide workspace scope, identity loss and
signed-out rendering. Source review found that the native Provider producer still
returns every discovered model under chat and an empty embedding directory.
Discovery supplies IDs without capability metadata. An explicit revision-bound
Provider embedding declaration is required; model names cannot establish that
capability. This remains a real native embedding acceptance blocker.

The complete Desktop run including the capability, selection and catalog wiring
passed 4,582 tests, skipped two binary-gated cases and retained one audited-source
parity failure (`/tmp/native-inputs-full.log`). Both renderer and test TypeScript
configurations passed. The polluted earlier log named
`memories-route-full-final.log` must not be used as evidence. A new full regression
and regenerated parity evidence are required for the final source baseline.

## Continuous scheduler ownership

`beab7d137` renews owner leases independently of control polling and admitted run
execution. Losing ownership stops new control admissions while an already
admitted runtime keeps its own run lease. Storage admission accepts an older
snapshot only when the database still has the same nonce and epoch, an expiry at
least as recent, and an unexpired database-clock lease. Renewal and release retain
exact compare-and-swap checks. `de0619b26` bounds owner release so a stalled release
cannot hang shutdown indefinitely.

The main scheduler-focused run passed 30 tests
(`/tmp/followup-main-owner-lifecycle.log`). Isolated implementation validation
included 52 adapter tests, three PostgreSQL cases and 50 server tests, covering a
blocked tool, owner loss, cancellation and durable human-input resume. This does
not establish deployment verification, reverse drain or joint cloud/native
scheduler acceptance. No live deployment was activated.

## Remaining acceptance boundaries

Default production knowledge release remains closed. Real local CRUD, indexing,
embedding, extraction and bidirectional synchronization need native acceptance;
model-backed operations must use the existing Provider and application vault.
Cloud/native enrollment and joint synchronization release are still incomplete.
The native QA host profile and actual catalog producer require separate review
before those journeys can run. External deployment verification and production
targets remain prerequisites for release-level automation acceptance.

Source review, focused tests and normal commit
checks provide the available evidence. Revert UI and transport commits independently
while preserving stored content, receipts, index builds and synchronization state.

## Native source navigation

Entity results can open relationships from the same exact source revision, and
relationship endpoints can open the source's entities with the selected reference
marked. These views retain all records from that source and use the existing bounded
pagination; they do not claim to be a complete graph or an entity-filtered query.
Only references in the current result can initiate navigation. Source revisions,
tenant/project identity and generation remain bound through every page, and a changed
or deleted source cannot silently redirect to replacement content. Clearing the source
filter returns to project browsing on the next explicit retrieval.

Four new controller regressions failed before implementation. The final retrieval
controller/render suites passed 23 tests, and renderer plus both test TypeScript
configurations compiled. Native click-through acceptance is pending the next canonical
Electron restart. No storage, protocol or default release gate changed.

## Isolated native and Cloud synchronization acceptance

The canonical Electron launch at `82957ef41`, followed by renderer scope validation
at `cff15e320` and a complete canonical restart at `45c2d3ea6`, used the same
private QA profile and workspace. Real native extraction produced four entities
and three relationships from the current source. Entity-to-relationship,
relationship-to-entity and exact-revision original-content navigation passed in
Electron. This supersedes the pending navigation observation above.

The QA Cloud API uses real authentication and production memory/synchronization
handlers in a dedicated PostgreSQL schema, plus a separate local Neo4j instance.
It publishes the checked acceptance profile in a process-local V2 host. It does
not publish ROOT state, start workers or activate the default knowledge release.
Its three integration tests cover real membership rejection, CRUD, enrollment,
pinned public Web projection and same-metadata restart. See
[the QA entrypoint](../../scripts/qa_cloud_knowledge_sync_README.md).

The following journeys passed against this isolated service:

- Native account login, tenant/project selection, enrollment and association.
- Five explicit native pushes: an earlier create/update/delete sequence and a
  new memory's create/update. The queue reached zero; Cloud listed one live
  memory with its original ID, complete Chinese content and revision 2.
- Explicit paged pull replay produced no conflict for acknowledged local writes.
  A production Cloud HTTP edit to revision 3 then appeared in the native list.
- Concurrent local and Cloud edits produced a durable pull conflict. The review
  displayed local revision 4, common baseline 3 and remote revision 4. Choosing
  "keep both" preserved both bodies under separate IDs. An explicit push made
  both records visible through Cloud HTTP and the real Web memory UI.
- Normal native exit and canonical restart preserved both records, an empty
  outbox, the project association and the application-vault Cloud account.
  First-load status no longer reported an unexpected context change. The user
  must select and verify the remote target again before network operations.
- The Cloud API restarted with the same metadata and retained authentication,
  enrollment, memory revisions and both conflict copies.

Evidence files are `/tmp/native-knowledge-sync-pushed-cff15e320.txt`,
`/tmp/native-knowledge-cloud-pull-8268728fc.txt`,
`/tmp/native-knowledge-conflict-keep-both-8268728fc.txt`,
`/tmp/native-knowledge-keep-both-cloud-8268728fc.json`,
`/tmp/native-knowledge-restart-45c2d3ea6.txt` and
`/tmp/web-knowledge-sync-detail-45c2d3ea6.txt`. They contain QA content and public
identifiers, not credentials.

This is not full release acceptance. Actual Web editing exposed missing enrolled
mutation precondition headers; the UI retained its draft and displayed failure.
Native editing/synchronization also left some adjacent counters stale until a
manual refresh; backend source invalidation was verified correct. Those fixes,
remaining conflict/recovery cases, diagnostics, Cloud graph navigation, current
full-suite/parity regeneration and external scheduler deployment verification
remain open. Cloud extraction/indexing is not exercised by this worker-free API.

## Web mutations, deletion and restart follow-up

At `22219932c`, the same isolated dataset completed the following additional
journeys through the real Web and Electron interfaces:

- After the enrolled mutation transport fix (`2b08b338d`), the Web editor saved
  the original memory as revision 5. Native paged pull displayed that exact body.
- Web deletion of the conflict copy succeeded. Native pull consumed its tombstone,
  removed the copy and retained the original; the outbox remained empty.
- A normal Electron exit and canonical `make -C agi-stack run-desktop` restart
  retained the edited original and the deletion. The saved account and project
  association survived; explicit target selection and binding verified the new
  remote authorization before further synchronization.
- The next pull returned `applied: 0`, `conflicts: 0`, `has_more: false` and
  `next_cursor: 10`, without replaying deleted content.
- Adjacent processing counters refreshed after pull. The new diagnostic panel
  loaded its empty failure list; a populated failure/retry journey remains pending.

The graph module artifact update changed the compiled QA profile digest. Review
confirmed that only the profile digest and graph artifact digest changed. After
stopping the owned QA API, its temporary metadata was backed up and advanced with
an expected-old-digest check. The same database schema, authentication and content
were retained. The service then restarted against the newly compiled profile;
no production profile or database content was rewritten to bypass validation.

Evidence: `/tmp/web-knowledge-sync-edited-2b08b338d.txt`,
`/tmp/native-knowledge-web-pull-6d04caa74.txt`,
`/tmp/web-knowledge-delete-6d04caa74.txt`,
`/tmp/native-knowledge-web-delete-6d04caa74.txt`,
`/tmp/native-knowledge-restart-22219932c.txt`,
`/tmp/native-knowledge-profile-rebind-22219932c.txt` and
`/tmp/cloud-knowledge-qa-profile-transition-22219932c.json`.

The Desktop full suite at `22219932c` finished with 4,697 passed, one failed and
two skipped (4,700 total). The failure is the reviewed Web redirect source hash
in `desktop-parity-reviewed-additional-web-entries.test.mjs`; its audit evidence
is stale. This run is not a green full-suite or release gate. Log:
`/tmp/desktop-graph-22219932c-full.log`. Graph interactions, metadata/schema/entity
synchronization, Agent source citation and the remaining release scenarios still
require their own evidence. The default knowledge release remains closed.

## Web graph provenance with persisted QA data

At `f73439066`, the isolated QA API was restarted with the production graph read
routes admitted. The declared fixture was seeded through the public Neo4j
persistence adapter into the dedicated loopback QA graph, after validating the
existing QA project and memory through SQL repositories. No memory, revision,
sync cursor or profile digest was changed by this fixture operation. The fixture
tests passed 15/15 on this main revision.

The real Web client loaded five nodes and seven edges. Canvas selection and
keyboard activation of the accessible relationship list verified:

- Distinct same-name entities retain their UUIDs and directed endpoints; selecting
  entity B shows incoming A-to-B and outgoing B-to-A relationships correctly.
- The linked source reads `QA_GRAPH_CAPTURE_V1` through its exact UUID. Opening
  the separately labeled current memory shows revision 5 and `WEB_SYNC_BODY_V3`.
- Selecting a missing source after a valid source clears the old source content
  and removes the current-memory link.
- The reverse relationship reads `QA_GRAPH_UNLINKED_V1` and offers no fabricated
  current-memory link. Community membership has no recorded source reference.
- The self relationship appears once in entity A's adjacency.

Local evidence is `/tmp/cloud-graph-fixture-f73439066.json`,
`/tmp/cloud-graph-fixture-f73439066.log`, and `/tmp/web-graph-*-f73439066.txt`
(captured, current-memory, forward-source, missing-source, directed-neighbors,
unlinked-source, membership and self-adjacency).

These observations prove graph transport and provenance browsing with a declared
fixture, not extraction or community generation. Native graph acceptance and the
populated native failure/retry journey remain pending: the current Computer Use
capture showed inconsistent screenshot/accessibility state and no verified result
from its attempted settings actions. No Provider endpoint was changed. This documentation records the observed UI and completed tests without claiming release-gate success.

## Native populated extraction failure and explicit recovery

The canonical Electron restart at `fcc0f16df` restored consistent Computer Use
interaction. In the isolated native QA profile, memory
`5f74c60e-e948-4bf1-b552-1c764805ac84` retained revision 1 and its original content
when its configured model endpoint became unavailable. The real native flow
selected a workspace, reviewed one extraction, and confirmed it. Attempt 1
failed with a connection error and remained visible in extraction diagnostics.

The test used a temporary loopback model-list endpoint so the native Provider
connection probe could complete, then stopped that owned server before extraction.
After observing the failure, the original Kimi endpoint and `kimi-for-coding`
default route were restored through the UI; the temporary model was disabled.
No API key was read or changed. An earlier invented model identifier had been
accepted by the real provider and produced a successful extraction, so it is
explicitly not evidence of a failed-model path.

Selecting the failed task and confirming recovery changed it to pending without
running the model. A separate workspace selection, single-task review and explicit
confirmation executed attempt 2 through the restored provider. The native receipt
showed the same memory and revision, attempt 2, and applied status. Coverage then
showed two applied sources, zero pending and zero failed. Vector coverage remained
zero of two and is not part of this recovery pass. Electron exited normally after
the task completed.

Local evidence: `/tmp/native-knowledge-failure-fcc0f16df.txt`,
`/tmp/native-knowledge-retry-pending-fcc0f16df.txt`, and
`/tmp/native-knowledge-retry-applied-fcc0f16df.txt`. This completes the populated
extraction failure/retry journey previously pending above. Native graph acceptance,
Agent citation, portable schema/entity/relationship records, and the shared release
gate remain separate outstanding work.

## Native Agent semantic source citation

At `316631c85`, the canonical Electron launch upgraded the same isolated profile
and retained both memories and applied extraction states. Two explicit single
index operations built current vectors with `bge-m3:latest` (1024 dimensions),
reaching 2/2 coverage without a failed index task. The query "Which project keeps
its notes available if its AI provider cannot be reached?" returned the recovery
sample first (cosine similarity 0.5658). Opening its exact match showed memory
`5f74c60e-e948-4bf1-b552-1c764805ac84`, revision 1, change 12, extraction attempt 2
and the preserved Cedar/Mira source text.

The real Kimi native conversation `5a4c894c-3b53-5a81-97a1-46f54150ee05` submitted
a five-step structured plan. After explicit approval with the read-only permission
profile, it called `knowledge_search` in semantic mode and then `knowledge_source`
with reference `0091488b-a9f8-429d-821c-11135bfb7ff7` returned by that search. Both
durable tool observations succeeded. The source audit retained the same source,
attempt, vector build, configuration revision and input digest as the search audit.
The final native answer named Cedar and Mira and cited that memory and revision.
The run reached review, then completed after its evidence was checked and approved
through the native UI. No file or knowledge write tool was called in this run.

The UI capture initially lagged the persisted result; raising the native window
showed the completed response. This was not treated as model failure. A separate
display regression split act/observe pairs around knowledge audit events, leaving
completed calls labeled running. The narrative model now pairs across that explicit
audit event type while preserving its separate record. An audit alone cannot mark
a call complete, error observations remain failed, and conversation messages still
bound pairing. The new regression failed before the change; native HMR subsequently
showed both knowledge calls completed.

Local evidence: `/tmp/native-index-two-sources-316631c85.txt`,
`/tmp/native-semantic-source-316631c85.txt`,
`/tmp/native-agent-knowledge-success-316631c85.txt` and
`/tmp/native-agent-knowledge-durable-316631c85.json`. The last file is a scoped
timeline export from a temporary, stable database/WAL copy; no live database was
modified. These observations do not cover background recovered/promoted runs,
which do not inherit the new explicit-run knowledge grant.

Combined authority tests passed 131 with one ignored; generated protocol and
native knowledge contract checks passed. Full Rust completed with 801 passed and
one ignored using four test threads. Two preceding default-concurrency runs each
had a timing failure (MCP delete timeout, then PTY EOF); those failures remain in
their logs. Desktop full at this revision had 4,718 passed, two failed and two
skipped: stale parity evidence and an obsolete aggregate lease-event assertion.
This is not a completed shared release gate.

## Portable metadata, native recovery and community processing

Current verification follows executable tests and native behavior checks. The
historical parity and manual promotion requirements above were retired; they are
not prerequisites and must not be recreated.

Native and Web editing now preserve user metadata as a JSON object, separately
from record tags. Invalid objects retain the draft without sending a mutation.
Web's detail sidebar also reads the persisted record tags rather than an unrelated
`metadata.tags` field. The editor submits the displayed revision through the
existing memory command path; a conflict retains the draft.

The isolated native memory `Native Metadata QA 20260908` was created with nested
arrays, a boolean, a decimal and null, then pushed to the real Web memory page.
The Web editor added a record tag and changed the nested object; incremental
pull advanced the local memory to revision 3 without a conflict. The native
detail showed `WEB_METADATA_V3`, `approved: true`, `score: 3.75` and the added
`web-reviewed` label. A complete application quit and canonical Make restart
preserved those values. The native storage lifecycle produced a schema-12 backup
before migrating to schema 13; both databases passed SQLite integrity checks
and retained the same scoped QA memory payload. A new semantic query after restart
again returned the Cedar source and its exact revision and extraction attempt.

The portable schema document foundation has matching Python/Rust structural and
revision validation. Its cloud command integration and native persistence are
separate ongoing batches; schema synchronization is not complete.

Community processing now uses the existing scoped knowledge authority and native
Provider configuration. A structured Agent submission supplies names, summaries,
rationale and exact source references. The worker persists accepted output and
sanitized attempt metadata under the same generation, current graph and lease
checks. Raw rejected model output and credentials are not included in the
presentation response. Creating or processing candidates never implicitly
publishes a build: selecting and activating it are separate revision-checked
commands. Source changes hide stale active output.

The Desktop community page supports candidate and build-history pagination,
explicit Workspace selection, processing one candidate, retrying a failed attempt,
activation and audit details. Build history lists immutable creation receipts;
opening a build reads its current processing state. The history query also makes
an accepted but unselected build discoverable after application restart or loss
of its creation response. While the controller retains an uncertain creation
request, its explicit recovery action uses exactly the same idempotency key and
parameters. It never silently creates a replacement request.

The new page has executable controller and rendering coverage, but its real
Electron interaction and community restart journey have not yet been exercised.
The earlier native metadata/extraction/retrieval results do not establish this
new community acceptance. The latest metadata source was separately extracted
and indexed through the native UI, bringing current vector coverage to 3/3.

Validation completed for the community transport/history/page batches: Desktop
4,491 passed, zero failed, two skipped; sidecar 811 passed, zero failed, one
ignored; device storage 192 passed; generated contract tests 49 passed. Two
real sidecar process integrations also passed without skips. The Rust-produced
four-query/one-command response fixture passes the actual Desktop HTTP consumer
and negative relationship checks. Electron compilation/build and strict Clippy
passed. The ongoing full Backend run has a tenant-deletion failure and is not a
passing full-suite result.

Earlier Web validation remains 3,692 tests, with 13 metadata editor/detail
regressions; the schema Python/Rust differential foundation passed 92 tests.
Source inspection, staged
diff checks, credential scans and executable tests bounded these changes.

Rollback can remove the community page and transport capabilities without
deleting immutable builds, attempts or accepted results. Preserve the existing
versioned knowledge database and pre-upgrade backups; older storage binaries must
continue to reject a newer schema. This is implementation progress, not completion
of I0–I6 or permission to open the shared first-release gate.

## Integrated schema commands and local Cron producer control

The portable schema foundation now has isolated native storage and cloud command
admission. Cloud bootstrap, replacement and the existing entity/edge/mapping
editing APIs share project locks, revision checks and immutable receipts. Replaying
an accepted HTTP mutation returns its original response after later edits or
deletion. Invalid JSON values fail before mutation; database guards reject forged
materializations and changes to accepted receipts. Native storage retains scoped
snapshots and receipts across reopen, with authorization and generation checks
around storage waits and before commit. Public native schema actions and schema
synchronization are not yet enabled. Full-document transport is a subsequent batch.

Community management and source graph browsing are integrated. Graph selection,
adjacency and source details use stored extraction provenance; they do not invent
relationships or silently classify records. Real Electron acceptance of the new
community and graph pages remains outstanding.

The local Cron closure adapter serializes schedule registration with the persisted
prepare barrier, including first startup when the global owner row is absent.
It removes only explicitly identified canonical Cron schedules and preserves the
shared scheduler, unrelated schedules and accepted executions. PostgreSQL and
APScheduler tests retain HITL requests/snapshots and resume an accepted execution
after closure. Administrator-only inspection and close endpoints use the existing
V2 operation and service authority. Inspection distinguishes the responding process
from the shared scheduler datastore view. A lost close response is recovered by
reading current state, not by manufacturing an operation receipt.

These endpoints do not discover a complete worker roster, verify external closure,
or activate the replacement scheduler. Cross-deployment addressing, trusted source
identities and the remaining execution/queue/HITL drain still need implementation
and deployment inputs. Rollback must retain the persisted barrier and receipts;
reverting UI or control endpoints must not reopen both scheduler authorities.

The completed Backend full run recorded 16,990 passed, 39 failed and 267 skipped
in 2:02:55 (`/tmp/backend-full-followup-restored.log`). The failures involved obsolete
V2 test setup, missing PostgreSQL reprocessing fixtures, asynchronous benchmark
requests and an outdated bootstrap entry count. All affected files plus the new
Cron closure tests subsequently passed together: 90 tests in 400.40 seconds
(`/tmp/qa-integrated-backend-repairs.log`). This targeted repair does not change
the original full run into a pass or replace a later complete run.

Integrated schema regression passed all 274 tests, including the Python/Rust
differential probe (`/tmp/qa-integrated-schema-full.log`). Desktop passed 4,502
with zero failures and two optional integrations skipped. Rust sidecar passed 826,
failed one macOS PTY cleanup test and ignored one optional renderer integration
(`/tmp/qa-integrated-sidecar-full.log`). The PTY permission error was reproduced
under stress; an isolated 17-test pass does not resolve it. Real process checks
and the remaining native acceptance journeys are still required.

## Full-document schema transport and macOS cleanup follow-up

Cloud schema reads, full-document replacements, actor-scoped receipt recovery and
bounded contiguous history now use a closed transport contract. Mutations retain
body-only revision conditions; conditional HTTP headers are rejected. The native
schema RPC boundary retains exact receipts, response-size preflight inside the
write transaction and dedicated action admission. These commands remain closed
in production while schema synchronization is being implemented. Cloud bootstrap
preview and race-safe initialization are the next batch.

The native write implementation now has a private transaction-scoped operation.
Existing public methods retain their authorization/deadline callbacks and own the
commit. A composed operation can roll back both journal and head if a subsequent
step fails. No synchronization cursor or additional project association is created
by this refactoring. All 23 schema storage integration tests, the new transaction
rollback test and strict device Clippy passed.

The macOS PTY investigation proved a snapshot race: a member can move to a new
process group within the retained session before cleanup inspects it. Cleanup now
follows that verified group, including children forked after the snapshot. A real
process barrier verifies both generations are terminated. The libproc adapter also
distinguishes an empty successful result from zero-return failures, captures errno
immediately and rejects partial process-info structures. Permission errors remain
visible. Test fallback cleanup rechecks indirect process identities before signalling.

Integrated validation: schema Python tests passed 329 with one optional probe
skipped; the explicit Python/Rust probe run passed all 92 contract tests. Desktop
passed 4,575 with three optional tests skipped. Sidecar passed 842 with one optional
renderer integration ignored; that Rust-to-Node real transport integration then
passed explicitly. Both real sidecar/workspace-core process tests passed without
skips. The final PTY production code passed 24 focused tests and 100 migration
barrier repeats. A separate 100-round, 16-thread stress run recorded 2,397 passing
cases and three `openpty -6` initialization failures. It did not reproduce raw
`EPERM`, but the original raw permission failure remains unassigned; this is not a
claim that the stress suite is fully passing.

Rollback may remove the new transport entry points or revert the private transaction
refactoring without deleting schema histories. Preserve the versioned knowledge
database and accepted receipts. The complete Backend rerun, live native community
and graph acceptance, schema synchronization, and the remaining I0–I6 work are
still outstanding.
