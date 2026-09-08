# Closed cloud schema storage foundation

Migration `32ed76ad9e43`, following `7c90e5134285`, adds storage structures and
read-only legacy inspection. It does not enable schema synchronization or an
accepted project-schema document. The original `entity_types`, `edge_types`
and `edge_type_maps` tables remain the sole current authority.

The later [internal command foundation](internal-commands.md) adds explicit
bootstrap/CAS and database guards in a separate migration. The description below
records the closed behavior of this original foundation revision.

## Database scope

The migration adds `project_schema_heads`, `project_schema_tombstones`,
`project_schema_changes`, `project_schema_receipts`, and
`project_schema_migration_findings`. It inserts no rows, backfills nothing,
and adds no defaults-on-read, bootstrap, API, service registration, or write
command. There is no writable current-document JSON column. The JSON snapshot
column belongs only to the future change journal.

The new `projects(id, tenant_id)` unique key supports composite scope foreign
keys. Because `projects.id` is already the primary key, it imposes no new
business uniqueness rule. Existing schema-table UUIDs, fields, nullable values,
timestamps, raw JSON text and the three existing name/triple unique constraints
are untouched.

A head can only be an inactive slot: `mode=legacy`, no schema ID/revision,
sequence zero and `deleted=false`. `ck_project_schema_head_closed` enforces this
in PostgreSQL, rather than relying on a configurable runtime flag. Heads are
not created automatically for existing or new projects. Required foreign keys
from journal/receipt/tombstone rows to a non-null head schema ID prevent accepted
history from being inserted while this closed constraint remains in place.

The journal/receipt/tombstone models describe future storage shape, not a
completed write protocol. Atomic CAS, immutable-history guards, project DML
fences, sequence allocation, replay and activation are not implemented here.
Enabling them requires a later migration and a unified command authority; the
closed constraint must not be removed independently to activate a project.

## Read-only inspection

`SqlProjectSchemaInspection.inspect(tenant_id=..., project_id=...)` performs one
scope-restricted `UNION ALL` query containing the project existence marker and
the three legacy tables. All returned rows therefore belong to the same SQL
statement snapshot. It disables ORM autoflush, selects columns rather than
ORM entities, and neither commits nor rolls back the caller's transaction.
It has no call to `dynamic_schema` or the default-type initializer.

The caller supplies an authorized read session. Exact tenant/project filtering
prevents cross-scope reads, but this standalone service does not establish the
caller's membership or expose an HTTP endpoint. It raises
`ProjectSchemaInspectionScopeNotFound` for an absent or mismatched scope.

The immutable report contains counts, structural codes, original record IDs,
field names and related record references. It allocates no UUID, proposes no
replacement identity, and writes neither findings nor a head. Names are matched
by exact equality; missing and ambiguous references remain errors. Source labels
are read as declared data and are not inferred or classified.

Codes include `legacy_schema_id_invalid`, `legacy_schema_id_collision`,
`legacy_schema_name_collision`, `legacy_schema_field_invalid`,
`legacy_schema_definition_invalid`, `legacy_schema_reference_missing`,
`legacy_schema_reference_ambiguous`, `legacy_schema_scope_invalid`,
`legacy_schema_member_limit_exceeded`, and
`legacy_schema_document_limit_exceeded`. A report is not an activation approval.

Definition JSON is selected as text so duplicate keys can be detected without
silently normalizing the stored representation. The existing portable bounds
apply to parsed values. A nullable legacy description is checked as an empty
portable description, without updating the old row. Historical physical
deletions cannot be reconstructed and no tombstones are invented.

## Verification and rollback

The integration suite requires a dedicated PostgreSQL database named
`memstack_schema_storage_qa` on loopback, supplied through
`PROJECT_SCHEMA_POSTGRES_TEST_URL`. It creates a random private SQL schema and
removes it after each test. The repository's historical baseline migration is
empty, so dependency tables are bootstrapped using Alembic autogeneration;
the actual new revision is then applied, reversed and applied again.

```sh
PROJECT_SCHEMA_POSTGRES_TEST_URL=postgresql+asyncpg://postgres@127.0.0.1:PORT/memstack_schema_storage_qa \
  uv run pytest --noconftest src/tests/integration/test_project_schema_storage.py \
  src/tests/unit/domain/model/project_schema/test_inspection.py
```

Tests verify old row/raw-JSON preservation, existing uniqueness, model/DDL
agreement, blocked activation, composite tenant scope, downgrade protection,
read-only transactions with dirty ORM state, real malformed legacy rows, empty
projects remaining empty, and the unchanged legacy write service. No native
or bidirectional schema-sync acceptance is claimed.

The new revision was generated with Alembic autogenerate and reviewed. Its
project scope unique key is created before dependent foreign keys and removed
after them on downgrade. The CLI upgrade/downgrade path was also exercised
against an isolated PostgreSQL instance. CLI configuration follows the current
repository `.env` DATABASE_URL authority; environment overrides alone do not
select a different database.

Downgrade removes only the new tables and redundant project scope key. It
refuses to run if findings, changes, receipts or tombstones contain data, rather
than erasing it. Empty legacy head slots may be removed. No old schema data is
repaired or deleted. Before any future activation release, add the command
authority and write fences for HTTP CRUD, default initialization and discovered
types together; an old unversioned writer must not become a fallback.
