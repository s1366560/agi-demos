# Internal cloud commands and database fences

Migration `1a3218f58274`, following the closed foundation `32ed76ad9e43`,
introduces an internal PostgreSQL command executor and complete transaction
fences. It creates no heads, initializes no types and activates no project.
There is no HTTP route, plugin registration, default initialization binding,
discovered-type binding, native integration or schema sync transport in this
batch. Existing projects remain legacy until an explicitly authorized internal
bootstrap command is invoked.

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
unrelated caller's ORM session. A future operation-scoped plugin must explicitly
adapt its unit-of-work and authorization boundary; no global-container or
unversioned-writer fallback is supplied.

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

Before any user project is activated, the next integration must route old HTTP
CRUD, explicit default initialization and discovered-type writes through this
same CAS boundary, make active reads free of initialization, and supply real
operation-owned authorization. Until then, legacy writes to an active test
project deliberately fail instead of bypassing the command protocol.

Schema outbox/prepared requests, receipts for transport, remote cursors,
verified source-to-target scope remapping, and schema capability enrollment
remain separate future work. They must not reuse Memory metadata, sequence,
outbox or cursor state. There is no extraction schema pinning or native
bidirectional acceptance claim in this batch.
