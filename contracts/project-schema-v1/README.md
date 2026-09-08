# Project schema document v1: contract foundation

Status: standalone domain contract only. No database, API, local authority,
sync transport, generated native-knowledge artifact, or extraction integration
uses this document yet. Metadata synchronization is a separate existing feature.

## Identity and structure

The required envelope is `format_version: 1`, `tenant_id`, `project_id`,
`schema_id`, `revision`, `deleted`, `entity_types`, `edge_types`, `mappings`,
and `tombstones`. Unknown or omitted fields fail closed. Scope IDs are opaque,
nonempty strings with no leading/trailing ASCII space, tab, CR or LF. Parsing
does not establish project membership, device enrollment, or write authority.

The document and every member use distinct, canonical lowercase, non-nil UUIDs.
IDs are supplied by a future trusted creation/import boundary; this module does
not generate IDs or derive them from labels. Entity and edge types contain `id`,
`name`, `description`, an opaque JSON-object `schema`, `status`, and `source`.
Mappings contain `id`, `source_type_id`, `target_type_id`, `edge_type_id`,
`status`, and `source`. All references must point to live members of the correct
kind in this same snapshot, including references to explicitly disabled types.
Status is `ENABLED` or `DISABLED`; source is a declared string, not an inferred
classification. Empty descriptions are valid; missing/null descriptions are not.

Names need not be unique. Name changes do not change member identity. Mapping
identity is its UUID; this contract does not deduplicate equal endpoint triples.
No keyword in the supplied `schema` is evaluated, and `$ref` values do not cause
file or network access. Deciding whether a schema is appropriate, whether two
types mean the same thing, or how to classify extracted data requires an agent
structured tool-call with the audit fields required by AGENTS.md.

## Revision, CAS and deletion

`revision` is a positive integer JSON token, at most `2147483647`. Members have
no independent CAS versions. `validate_successor` checks an entire replacement
document against an explicit previous document and `expected_revision`:

- Creation uses expected revision 0, accepted revision 1, `deleted: false`, and
  no tombstones. A nonempty initial document is permitted.
- Updates preserve scope and schema ID and advance exactly one revision.
  Exhausted revision space rejects further updates.
- A surviving member ID retains its kind. A removed member requires a tombstone
  with that ID, original kind, and the new document's revision.
- Tombstones contain `id`, `kind` (`entity_type`, `edge_type`, or `mapping`),
  and `deleted_revision`. They remain unchanged in every later snapshot. Deleted
  IDs cannot be reused, moved to another kind, or silently omitted.
- Document deletion sets `deleted: true`, removes all live members and retains
  all previous and newly required tombstones. This document identity is terminal.
  A later new document would require a new, explicitly authorized identity.

A standalone snapshot can contain historical tombstones no newer than itself.
Only adjacent-version validation can prove their history. Neither parser nor
`validate_successor` performs an atomic database CAS. A future repository must
load and compare the accepted revision in the same transaction as its write.
The helper also does not resolve conflicts or imply that a presented base is
trusted. The error codes are `project_schema_document_invalid`,
`project_schema_transition_invalid`, and `project_schema_revision_conflict`.

## Portable bounds

`document.schema.json` specifies the Draft 2020-12 shape. Its `x-*` annotations
are additional normative checks implemented by both language validators:

| Constraint | Limit |
| --- | --- |
| Incoming UTF-8 JSON bytes | 1,048,576, including whitespace |
| Document serialization weight | 1,048,576 |
| Total live members plus retained tombstones | 1,024 |
| Scope IDs and names | 512 UTF-8 bytes each |
| Description / source | 4,096 / 128 UTF-8 bytes |
| Each type's schema JSON nodes | 1,024; root and every value count once |
| Each type's schema nesting | 16; object root is depth 0 |
| Each type's schema key/value string bytes | 16,384 total UTF-8 bytes |
| Schema numbers | Finite binary64-compatible values in ±(2^53 − 1) |

The serialization weight counts compact JSON punctuation and UTF-8 string
escaping, reserving 32 bytes for every number irrespective of its lexical form.
This gives both implementations the same upper bound even when they format a
float differently, and keeps normalized output within the byte limit. String
quotes/backslashes and the five short control escapes cost two bytes; other
ASCII control escapes cost six. Other UTF-8 bytes cost one. Containers, commas,
colons, `true`, `false` and `null` have their usual compact JSON lengths.

Duplicate object keys at every depth, nonfinite numbers, lone surrogates, and
NUL in stored strings or keys are rejected. UUIDs, revisions and format versions
are validated without coercion; `1.0`, `1e0`, strings, and booleans are not integer
tokens. Generic JSON Schema validators alone do not enforce these lexical,
cross-reference, cumulative-byte, or historical constraints. Tombstones consume
the member limit permanently in v1; no compaction/reset is authorized here.

Rust core enables serde_json's `float_roundtrip` feature. The differential test
found that the default parser changed `9007199254740991.0` by one. Cargo unifies
this feature in dependent build graphs; no additional package is introduced.

## Verification

Both languages consume `fixtures.json`. The Python suite additionally sends
boundary payloads directly to the Rust JSON-lines probe and compares acceptance,
error code, and returned document, including number values. The probe is a test
example, not a production endpoint.

From the repository root:

```sh
export CARGO_TARGET_DIR=/tmp/agi-schema-contract-target
export CARGO_INCREMENTAL=0
export CARGO_BUILD_JOBS=2
cargo test --manifest-path agi-stack/Cargo.toml -p agistack-core --no-default-features
cargo build --manifest-path agi-stack/Cargo.toml -p agistack-core --example project_schema_contract_probe --no-default-features
PROJECT_SCHEMA_RUST_PROBE="$CARGO_TARGET_DIR/debug/examples/project_schema_contract_probe" \
  uv run pytest --noconftest src/tests/unit/domain/model/project_schema/test_contract.py
```

Without `PROJECT_SCHEMA_RUST_PROBE`, only the direct differential test skips;
the Python fixture/boundary tests and Rust shared-fixture test still run.

## Future migration, compatibility and rollback

1. Introduce cloud storage only through Alembic and local storage through a
   versioned, transactional migration with a backup. Preserve existing type and
   mapping UUIDs. Map existing nullable descriptions to the explicit empty string
   representation only under a reviewed migration. Inventory any noncanonical
   IDs, oversized definitions and incompatible values before enabling writes.
2. Resolve legacy mapping names only by exact, unique project-scoped matches.
   Missing or ambiguous references require repair; do not guess or merge by name.
   Existing SQL name/triple uniqueness is narrower than this ID-based contract.
   A compatibility adapter must explicitly reject unrepresentable writes until
   the old consumers and constraints are migrated; do not silently drop members.
3. Route all old and new schema writes through one authority and atomic CAS before
   enabling synchronization. Add a dedicated versioned journal, receipts, outbox
   and cursor; do not overload memory metadata or the current memory journal.
   Immutable prepared requests and receipts must survive retries and upgrades.
4. Bootstrap local/cloud identity explicitly. Add local CRUD and conflict UI,
   then real Electron/Web bidirectional and failure/restart acceptance. Pin each
   extraction run to the selected schema ID and revision before claiming shared
   extraction semantics. Semantic reconciliation requires an audited agent call.

This foundation can be rolled back by reverting its code, fixtures and docs:
no persistent state or existing endpoint behavior has been migrated. After a
future storage/authority rollout, rollback must disable writes, retain journals,
receipts and tombstones, and restore or forward-migrate a verified backup. An old
writer must never resume against a new schema while bypassing CAS. No destructive
down-migration or tombstone erasure is authorized by this document.

Entity/relationship record synchronization, portable provenance, database
migrations, runtime authorities, transport/enrollment, UI, extraction, vectors,
indexes, processing tasks and leases remain unimplemented by this batch.
