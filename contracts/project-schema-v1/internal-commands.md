# Internal cloud commands and database fences

Migration `1a3218f58274`, following the closed foundation `32ed76ad9e43`,
introduces an internal PostgreSQL command executor and complete transaction
fences. It creates no heads, initializes no types and activates no project.
The M0 integration below binds existing HTTP reads to live operation-owned
authorization and makes active reads pure. It adds no public bootstrap route,
schema enrollment or sync transport. M1 adds the bounded HTTP patch adapter
described below. Existing projects
remain legacy until an explicitly authorized internal bootstrap command is invoked.

## Internal boundary

`SqlProjectSchemaCommands` requires an explicit session factory and a
`ProjectSchemaAuthorization` implementation; there is no permissive default.
`ProjectSchemaScope` carries tenant, project and actor IDs. The authorization
port must raise unless the actor may perform the exact `read`, `bootstrap` or
`replace` action in that scope. It is called before database work and again
before transaction completion, including receipt replays. Database project
ownership is checked separately and cannot be bypassed by a permissive test
authorization stub.

Each command owns an isolated session and transaction, acquires the project
row lock, and returns only after commit succeeds. This does not flush an
unrelated caller's ORM session. The M0 schema plugin supplies a live operation-owned authorization adapter.
M1 binds the existing public mutation routes through its isolated command
adapter; no global-container or unversioned writer fallback is supplied for active schemas.

- `read(scope)` returns a validated relational snapshot for an active head,
  or `None` for a legacy project. It creates neither a head nor defaults.
- `bootstrap(scope, BootstrapProjectSchema(schema_id, change_id))` uses an
  explicit document identity and stable request ID. It re-inspects the actual
  locked legacy rows, rejecting the entire batch for any structural finding.
- `replace(scope, ReplaceProjectSchema(document, expected_revision, change_id))`
  validates the complete adjacent replacement and applies it atomically.

Bootstrap preserves every existing member UUID. Name references resolve only
by exact unique project-scoped equality. The SQL head guard independently
compares the admitted bootstrap document with the actual pre-activation rows,
so a forged replacement ID cannot substitute for a legacy identity. Invalid
UUIDs, duplicate IDs, malformed or duplicate-key JSON, missing references and
ambiguous references cause rejection without repair or partial activation.

Nullable legacy descriptions project to the portable empty string without
rewriting the old values during bootstrap. Opaque JSON numbers project through
the contract's binary64 representation; original legacy JSON text stays intact.
Historical physical deletions produce no invented tombstones.

## Single current authority

`entity_types`, `edge_types` and `edge_type_maps` remain the current live rows.
Mapping rows gain nullable `source_type_id`, `target_type_id`, and `edge_type_id`
columns. They remain NULL in legacy mode, are filled by explicit bootstrap,
and must reference the correct type kind in the same project once active.
The composite foreign keys are deferred so a complete command can atomically
swap names or replace mappings while preserving identities and creation times.

Legacy mapping names are compatibility fields, checked against the referenced
type names at commit; they cannot diverge from ID references. The old name and
mapping-triple unique constraints remain intact. Although document v1 permits
duplicate names and triples, the internal command rejects these with
`project_schema_legacy_unrepresentable` until old name-keyed consumers have
been migrated. No members are dropped or merged to fit the old representation.

The head contains identity/revision facts only. There is no writable current
JSON document. Immutable journal snapshots describe accepted revisions and are
verified against the relational current state within the accepting transaction.

## Commit protocol

1. Authorize the exact action, lock the project, and check the scoped receipt.
   Identical internal request JSON returns the exact persisted response text;
   reusing a change ID with different request JSON rejects. Replay precedes CAS.
2. Validate bootstrap or the adjacent replacement against the locked current
   revision. A project/schema identity is fixed after activation.
3. Register the structural command intent and advance the head once. The head
   trigger checks scope, expected revision, document structure, previous
   immutable history, and tombstone transitions. It then appends the journal
   and receipt itself, before any live row mutation is permitted.
4. Apply the complete relational changes and newly required tombstones.
   Deferred guards check the final head, same-transaction journal, receipt,
   complete reconstructed document, and mapping-name compatibility.
5. Recheck authorization and commit. Any row, history, receipt, authorization
   or deferred-check failure rolls back every command write.

Only one schema command per project per database transaction is admitted.
Revision and project sequence advance together in this first single-identity
implementation. Local/remote sync revision mapping is not implemented here.

A transaction setting alone is not a grant. Active row DML requires the
matching journal produced by the head trigger in the same PostgreSQL transaction.
Direct journal/receipt inserts are rejected, as are updates/deletions of accepted
history, tombstone changes, identity/scope moves and table truncation. Deferred
row checks remain effective after `SET CONSTRAINTS ALL IMMEDIATE`; a later write
cannot escape the accepted snapshot.

All legacy row writers acquire the same project lock before admission, so
bootstrap cannot race an unnoticed legacy commit. Ordinary PostgreSQL deadlock
or serialization errors remain transaction failures; callers must retry the
same immutable command explicitly. No automatic merge/rebase is performed.

These guards enforce database protocol invariants. They do not authenticate an
actor encoded in a SQL setting, and are not a security boundary against a DDL
owner/superuser that can disable triggers or replace functions. Application
actor authorization remains the required port's responsibility.

## Retirement and rollback

Deleting a schema document is a CAS command that removes live members and
retains all required tombstones, its terminal head, journal and receipts. That
identity cannot be restored or silently replaced by a new document identity.

An active project's physical deletion or tenant/ID move is rejected, including
after terminal schema deletion. Cascading project deletion must not erase
accepted schema history. An explicit future scope-retirement/retention protocol
is required for that operation. Empty legacy project deletion remains unchanged.

Downgrade to `32ed76ad9e43` is allowed only with no active heads, accepted
history, tombstones, receipts or populated mapping ID columns. It removes the
new functions/guards and reference columns and restores the database closed
CHECK. With accepted data it refuses rollback; preserve history and use a
reviewed forward migration or verified backup. Never enable an old writer as a
fallback against an active schema.

## Verification and next integration

The dedicated PostgreSQL tests cover migration upgrade/downgrade/re-upgrade and
metadata agreement; old row and raw JSON preservation; full rollback; explicit
authorization and denied replay; adversarial SQL and late writes; immutable
history; concurrent bootstrap/CAS; and stale legacy transactions around activation.

Run with the isolated loopback database described by the storage foundation:

```sh
PYTHONPATH=. PROJECT_SCHEMA_POSTGRES_TEST_URL=postgresql+asyncpg://postgres@127.0.0.1:PORT/memstack_schema_storage_qa \
  uv run pytest --noconftest src/tests/integration/test_project_schema_commands.py \
  src/tests/integration/test_project_schema_fences.py \
  src/tests/integration/test_project_schema_concurrency.py \
  src/tests/integration/test_project_schema_tombstones.py \
  src/tests/unit/domain/model/project_schema/test_commands.py
```

Before any user project is activated, M1 must route all eight existing HTTP
mutators through CAS with an immutable original request intent: operation,
target ID, provided fields, expected revision and change ID. Receipt lookup
must happen before materializing the patch against the locked current head;
created IDs are allocated only after excluding replay. Replaying a request
must return its original response, including response timestamps, rather than
reconstructing the result from a later mutable row. M1 must reauthorize before
commit. Explicit default initialization and discovered-type writes also need
an explicitly scoped command adapter or must remain unsupported for active
projects. M0 intentionally rejects these active writes.

Schema outbox/prepared requests, receipts for transport, remote cursors,
verified source-to-target scope remapping, and schema capability enrollment
remain separate future work. They must not reuse Memory metadata, sequence,
outbox or cursor state. There is no extraction schema pinning or native
bidirectional acceptance claim in this batch.


## M0: live authority and pure active reads

The existing schema dependency captures the request's pinned generation once.
A ROOT operation discovers the actual Project tenant using current active User,
UserTenant and UserProject membership rows. A PROJECT operation in that same
generation then owns the SQL session, exact tenant/project/actor scope and a
required `ProjectSchemaAuthorization` adapter. Optional tenant input must match
the discovered tenant. No URL-only scope payload grants membership. The adapter
checks operation lifetime, the captured generation object and descriptor,
identity and session before and after database authorization awaits. Reads
reauthorize after fetching their result, so observed membership revocation or
generation disposal prevents returning it. An older pinned but still live
generation is valid; publication of a replacement alone does not invalidate it.

For an active project, the three existing HTTP collection reads use one SQL
statement that reads the accepted document and original relational timestamps
from the same MVCC snapshot. Returned compatibility rows are detached objects;
no ORM row is added, flushed, initialized or cached by this path. Document
schema/revision/UUIDs and nullable-description projection follow the portable
contract. Corrupt document failures propagate as protocol failures; only actual
access-denied errors become HTTP 403.

Internal graph schema readers resolve the actual tenant and validate stored
scope without inventing an actor or command authorization. Their caller already
owns project access. They check active mode before the legacy 60-second cache,
return exactly the declared members and mapping UUID projections, and never
synthesize the seven defaults for active or terminal-empty documents. Prompt
indices are deterministic UUID-order projections, not portable member IDs.
The context includes the complete accepted document. Typed Pydantic models use
the existing legacy field projection; this does not redefine the opaque JSON
schema payload. Extraction-wide revision pinning remains future work.

Legacy graph reads retain their previous initialization and caching behavior.
A final active-mode probe after a legacy cache/database read selects a complete
active snapshot if concurrent enrollment is observed. If enrollment occurs
after that final probe, the read is linearized at the probe. It never merges an
active snapshot with legacy defaults. Legacy writers acquire the same project
lock as bootstrap before testing mode, avoiding a pass-check/enrollment race.

All eight HTTP mutators return HTTP 409 with code
`project_schema_command_required` for an active schema. Explicit default and
all discovered-type writers raise the same typed failure before no-op/dedup
returns. The graph discovery caller records `SchemaCommandRequiredV2` as a
warning and does not report created counts for that failed write. Legacy write
methods still commit internally; M0 does not claim authorization fencing at
legacy write commit or command replay support for those methods.

`test_project_schema_m0.py` covers live operation/tenant/member authorization,
mid-read user/membership revocation and generation/operation disposal, active
cache transitions, original response timestamps, terminal empty reads, typed
writer rejection and corrupt-document propagation through actual HTTP routes.
Run it with the same isolated PostgreSQL URL as above and normal repository
pytest fixtures (omit `--noconftest`) so unrelated runtime background workers
remain isolated during generation-host tests.

## M1: existing HTTP mutations with locked CAS and exact replay

Migration `bfa08f458c13` adds only immutable HTTP response receipts and new
frozen SQL guards. It does not activate projects. For an active project, all
eight existing entity/edge/mapping mutators now accept these two headers:

- `X-Project-Schema-Expected-Revision`: canonical positive decimal revision.
- `X-Project-Schema-Change-Id`: canonical nonzero UUID identifying the original request.

Both are required for active schemas (missing: 409 `project_schema_command_required`;
malformed: 422 `project_schema_precondition_invalid`). Legacy projects without
headers retain their existing writers. Any CAS header on a legacy project
returns 409 `project_schema_active_required`; preconditions are never ignored.
The executor locks the project before selecting mode, so a request waiting for
bootstrap observes the committed active head. Initialization and discovery writers
remain unsupported for active schemas.

The application copies only explicitly supplied DTO fields into immutable JSON
before its first await. Explicit null and omitted fields remain different request
identities, although null update fields preserve legacy no-op behavior. Nonfinite
numbers, invalid Unicode, invalid target UUIDs and candidate contract violations
are controlled 422 `project_schema_mutation_invalid` failures. Errors validating
stored authority are not reclassified as client mistakes. Create identities are
allocated only after an exact replay miss and successful locked revision check.
Mapping names resolve by exact unique equality inside that accepted document.
Referenced entity/edge deletion returns 409 `project_schema_type_referenced`;
callers must explicitly delete mappings first. There is no cascade or retry rebase.

`SqlProjectSchemaHttpCommands` owns an isolated transaction using the request's
actual bound async engine. The same captured operation, generation, actor and
scope authorize before SQL, after project-lock/head reads, and before active
commit or replay return. Legacy callbacks retain their internal commit behavior;
the post-lock authorization check runs before invoking them. This boundary does
not claim to fence revocations during a legacy callback's own commit.

A new SQL head guard independently materializes original HTTP intent and compares
it with the proposed full document. Current rows, adjacent head, base journal,
base receipt and HTTP receipt commit together. The database renders the response
from actual rows after materialization, including persisted timestamps, and
stores its exact body text, status (200 or empty 204), and schema ID/revision/change
headers. A five-part tenant/project/schema/actor/change key scopes replay. Reusing
a change ID for different intent returns 409 `project_schema_change_id_reused`.
An exact replay returns the original bytes and revision even after later updates
or deletion; it never rereads the current member to reconstruct that response.

HTTP receipts cannot be updated, deleted or truncated. Deferred commit guards
recheck receipt equality against final rows; later timestamp writes cannot leave
a stale receipt, including after constraints are made immediate. Downgrade refuses
accepted HTTP history. The older frozen migrations remain unchanged.

`test_project_schema_http_{api,commands,guards}.py` covers all eight actual routes,
concurrent identical creates, stale CAS, live authorization revocation, pending
unrelated ORM work, bootstrap races, malformed raw JSON, independent SQL
materialization, receipt immutability, commit-time drift and migration roundtrip.
This is cloud HTTP command support only: schema enrollment, native commands,
Memory synchronization and remote transport remain outside M1.

## M2 cloud full-document transport

Four authenticated POST routes under `/api/v1/projects/{project_id}/schema/document`
expose the existing full-document authority. `cloud-rpc.schema.json` defines their
closed request/response shapes: `read` takes `{}`; `replace` takes `document`,
`expected_revision`, `change_id`; `receipt` takes `schema_id`, `change_id`; `history`
takes `schema_id`, `after_revision`, `limit`. Actor and actual tenant come from the
request-pinned schema operation. No body-supplied identity or alternate target is accepted.

Read returns an accepted document or null for legacy plus the existing cloud knowledge
sync generation observation. Read may carry the optional generation condition; all
other operations require `X-Memstack-Knowledge-Sync-Generation`. Missing, malformed and
mismatched conditions return 428, 400 and 412. These operations do not require Memory
sync enrollment and do not initialize a schema. Generation JSON receives duplicate-key,
nonfinite and Unicode validation before descriptor parsing. Existing live pinned cloud
generation semantics apply; this transport does not substitute native lease semantics.

Raw request envelopes reject duplicate fields, nonfinite numbers, invalid UTF-8 or
surrogates, unknown fields, excessive nesting and payloads above 2 MiB. Their typed
validation failures return 422 `project_schema_transport_invalid`. Documents retain
their 1 MiB structural bound. Full replacement freezes supplied array order in request
identity and delegates atomic CAS to `SqlProjectSchemaCommands`; it never decomposes a
snapshot into per-item M1 calls. Legacy replacement, stale revision, terminal or invalid
successor, identity mismatch, reused change ID and legacy-unrepresentable snapshots
return typed 409 conflicts. The shared bootstrap/M1/full-replace change namespace remains
unchanged. Cross-scope document input returns 422; unauthorized access returns 403.

Replace and actor-scoped receipt lookup return the exact stored cloud receipt JSON bytes.
Missing receipt lookup returns 404. Cloud receipt fields remain `schema_id`, `revision`,
`sequence`, `change_id`, `document`; they are not rewritten into native's distinct receipt
shape. An exact replay returns the original accepted snapshot even after newer writes or
terminal deletion. A current read is not an acknowledgement. Future synchronization must
retain a source/destination receipt pair with independent revisions, not replace it with
a newer head or silently rebase a failed CAS.

History is project-readable across writers, under the same project lock used by commands.
It returns a same-transaction `upper_revision`, contiguous `receipts`,
`next_after_revision`, and `has_more`. `limit` is an integer from 1 through 100; the cursor
is an integer from zero through the locked upper revision. The entire serialized response
is at most 2 MiB, returning only a complete prefix. Admission reserves the longest cursor
and boolean envelope before accepting each receipt, then checks final bytes. Stored
receipt bytes remain intact inside the page. Empty and terminal histories are supported;
legacy history returns active-required. Missing rows, revision/sequence disagreement,
scope mismatch or malformed stored receipts are internal failures, never client 4xx
validation errors. Every query reauthorizes after locking and before return.

The operation reuses M1's factory-bound isolated sessions and authorization, so request
ORM state is never flushed. There are no new tables, migrations, bootstrap endpoint,
outbox, binding mechanism, transport client, scheduler, enrollment or activation changes.
Future schema sync must reuse the verified project association and trusted transport,
preserve one logical schema identity, and explicitly resolve independently active heads,
missing bootstrap/history and tombstone lineage. Latest-snapshot copying and revision
renumbering are not valid substitutes for that later protocol.

M2 rejects `X-Expected-Revision`, `Idempotency-Key`,
`X-Project-Schema-Expected-Revision`, and `X-Project-Schema-Change-Id`, including
duplicate occurrences, with 422 transport-invalid. The closed body is the sole CAS and
change-identity source. History cursors require nonnegative integer JSON tokens: `-0`,
`0.0`, `0e0`, and booleans are invalid. This envelope rule does not change opaque numeric
values inside document JSON Schema objects.
