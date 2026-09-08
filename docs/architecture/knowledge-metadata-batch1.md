# Scoped knowledge user metadata

The local knowledge authority persists user metadata in `KnowledgeMemory`, a scoped document type. The legacy `core::Memory` boundary remains unchanged. Existing cloud `MemorySyncContent.metadata` is the portable contract; this change introduces no new remote journal, field name, or release capability.

## Write and read semantics

- Create and update commands require an explicit JSON object. `{}` explicitly clears metadata; omission and `null` are invalid commands.
- Nested JSON values are retained. The serialized metadata object is limited to 65,536 UTF-8 bytes, matching the portable contract.
- Metadata participates in the same revision compare-and-swap, idempotency receipt, processing change, and sync outbox transaction as the document content.
- Get, list, accepted changes, and mutation receipts expose metadata. A later local edit cannot alter an older receipt or already prepared HTTP request.
- Pull applies metadata into the local document and accepted change without echoing it into the local outbox. Explicit local, remote, merged, and keep-both conflict choices retain the chosen metadata in both the document and any queued change.
- Derived entities, embeddings, extraction diagnostics, index state, and task state remain local and are not made portable by this field.

## SQLite version 12 upgrade

The existing native storage lifecycle backs up the previous database before migration. The migration runs in the existing schema transaction and does not migrate unattributed legacy rows.

For a document missing the field, the migration reads the newest explicit pending metadata intent for the same tenant, project, and memory. Otherwise it uses the trusted retained remote baseline, or an empty object if neither exists. An already present field is preserved.

For accepted changes, explicit metadata stored for that exact outbox sequence is authoritative. Only an unprepared pending change may otherwise use the retained remote baseline, matching the preparation behavior of the previous version. A historical or already prepared change without explicit evidence gets the historical empty default instead of claiming that the latest baseline was its original metadata.

Prepared HTTP request bytes, mutation request and receipt bytes, remote baselines, and conflict archives are not rewritten. Old mutation request comparison normalizes the historical omitted field in memory; it does not modify the durable request. Failed migration rolls back with the existing schema transaction.

## Validation boundary

The schema, generated TypeScript views, renderer checks, and Rust mutation deserializer require explicit object metadata. Persisted document deserialization alone permits the historical missing field. A raw native HTTP caller therefore cannot silently clear metadata by omitting it.

The default release gate remains closed. Regenerating the knowledge module artifact refreshes only the declared source digest and derived catalog/profile digests; acceptance profiles retain their existing scope and permissions.
