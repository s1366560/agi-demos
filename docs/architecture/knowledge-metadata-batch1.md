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

For a document missing the field, the migration first reads explicit outbox metadata matching the exact current tenant, project, memory, and local revision, even if that outbox change has already been acknowledged. Otherwise it reads the newest explicit pending metadata intent for that scoped memory, then the trusted retained remote baseline, or an empty object if none exists. An already present field is preserved.

For accepted changes, explicit metadata stored for that exact outbox sequence is authoritative. Only an unprepared pending change may otherwise use the retained remote baseline, matching the preparation behavior of the previous version. A historical or already prepared change without explicit evidence gets the historical empty default instead of claiming that the latest baseline was its original metadata.

Prepared HTTP request bytes, mutation request and receipt bytes, remote baselines, and conflict archives are not rewritten. Old mutation request comparison normalizes the historical omitted field in memory; it does not modify the durable request. Failed migration rolls back with the existing schema transaction.

## Validation boundary

The schema, generated TypeScript views, renderer checks, and Rust mutation deserializer require explicit object metadata. Persisted document deserialization alone permits the historical missing field. A raw native HTTP caller therefore cannot silently clear metadata by omitting it.

The default release gate remains closed. Regenerating the knowledge module artifact refreshes only the declared source digest and derived catalog/profile digests; acceptance profiles retain their existing scope and permissions.

## Native editing and conflict review

The native memory editor displays user metadata and exposes a JSON text field for create/update. The manual conflict merge editor uses the same field and validation. A malformed, non-object, or oversized value leaves the draft editable and does not start a write or consume an idempotency key. Repairing the field clears its validation message.

Only the parsed object enters the command. The UI's raw `metadataText` is never sent to storage. Once a write starts, the existing immutable command and scope fence cover metadata as well as the other fields; an unknown outcome locks the draft until explicit same-request retry. Context retirement clears both the parsed record and raw metadata draft.
