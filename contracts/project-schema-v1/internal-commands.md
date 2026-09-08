# Internal cloud commands and database fences

Migration `1a3218f58274`, following the closed foundation `32ed76ad9e43`,
introduces an internal PostgreSQL command executor and complete transaction
fences. It creates no heads, initializes no types and activates no project.
The M0 integration below binds existing HTTP reads to live operation-owned
authorization and makes active reads pure. It adds no public bootstrap route,
schema enrollment, patch command adapter or sync transport. Existing projects
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
Public mutation commands remain unbound; no global-container or unversioned
writer fallback is supplied for active schemas.

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
