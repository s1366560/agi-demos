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

GitNexus impact and change detection were attempted but returned Transport closed;
no graph validation is claimed. Source review, focused tests and normal commit
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
