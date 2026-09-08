# Local community build storage

The B1 batch persists community build inputs and work ownership. The later
[B2a result contract](knowledge-community-results.md) adds audited completion and
active-build storage; the boundaries below describe B1 alone. It does not
register a runtime action, call a provider, produce names or summaries, or
publish a community. Nonempty builds cannot be completed through this API.

## Atomic creation and fixed evidence

`CommunityBuildRepository` accepts an authenticated tenant/project scope and a
request containing actor ID, idempotency key and minimum community size. The
host must supply these identity fields and timestamps; a future renderer route
must not treat renderer identity or time as authority.

Creation captures all current sources and current successfully audited
projections using the batch A read transaction. It hashes and partitions the
snapshot outside the repository mutex. A write transaction then captures the
current graph again and compares its full fingerprint before inserting the
build, candidates, ordered member references and pending jobs together. A source
edit, deletion, metadata change or late extraction completion between capture
and insertion produces a conflict and leaves no partial build.

The build stores the entire snapshot, including full portable metadata,
processing coverage, source revisions and extraction audit evidence digests.
Candidate IDs are membership digests scoped to the build. Member references
retain source-local entity positions; equal names never merge identities.

An idempotency key is scoped by tenant, project and actor. Repeating the same
request returns its original receipt even after live sources change. Reusing
the key with different parameters conflicts. A caller must choose a new key to
request a new snapshot. SQL triggers reject updates to persisted build,
candidate and member inputs. Reads validate snapshot and membership digests,
scope bindings, positions and referenced source entities.

An empty candidate set creates a `completed_empty` receipt and zero jobs. This
means the fixed input produced no eligible structural partitions; it is not an
agent verdict on the quality or completeness of the project's knowledge.

## Jobs and leases

Each nonempty candidate starts with a pending job. A claim is scoped to one
build and chooses the next pending or expired job in stored candidate order.
SQLite's immediate transaction serializes claims across connections. Each
claim generates a new token and increments the attempt. A lease binds tenant,
project, build, candidate, graph digest, worker and attempt.

Renewal and failure transitions require the matching unexpired stored lease.
The stored deadline is authoritative, and renewal never shortens it. Failed
jobs require an explicit retry with the exact failed attempt; retry preserves
the frozen input. Reopening a database does not reset ownership or attempts.
An expired worker cannot mutate a reclaimed job even if it retains its original
token. Device methods check the trusted clock/admission callback under the
write lock and again before commit; expiry or changed admission rolls back the
whole transition. The trait adapter advances the trusted host timestamp with
monotonic elapsed time measured from invocation, including repository mutex and
SQLite write-lock waits. Hosts must supply a fresh timestamp at invocation.
Deterministic clock tests use the device callback methods directly; the adapter
never mixes that supplied clock epoch with the system wall-clock epoch.

A lease grants ownership of historical fixed input. It does not establish that
the graph is still current, and cannot authorize publication. Source changes
after build creation deliberately leave its historical evidence intact. The
next batch must add an audited semantic submission contract and current-graph
validation before publishing any output. There is no placeholder summary or
name-joining fallback in this batch.

## Schema and backup lifecycle

The existing knowledge schema advances from 12 to 13 in its normal migration
transaction. Four tables hold builds, candidates, members and jobs, with three
immutability triggers. A database already marked schema 13 must have these
objects; missing objects fail closed. A failed migration rolls back both its
partial objects and the version advance. Existing portable documents,
processing changes, extraction audits and sync outbox rows are not rewritten.

The native `knowledge_authority_v2/storage_lifecycle.rs` already derives its
target version from `KNOWLEDGE_SCHEMA_VERSION`. Its existing SQLite online
backup runs before an older database is opened for migration, includes
committed WAL data, checks integrity and retains the original schema version.
No second version authority or backup mechanism is introduced. Calling the
device repository directly is a lower-level operation and does not perform
filesystem backup; native activation must continue through the existing
lifecycle.

Disabling a future community runtime entry leaves all existing knowledge and
sync data intact. Schema-12 binaries reject a schema-13 database; rolling back
to an older binary requires an explicit compatibility/migration plan. Restoring
the pre-upgrade backup would discard subsequent knowledge/sync writes and must
not be used as an automatic feature rollback.

## Validation

Storage tests cover fixed-input replay across metadata edits and restart;
candidate/member/job insertion rollback; stale-snapshot CAS for edits and late
completion; empty build receipts; tenant/project/actor isolation; concurrent
claims; expired-token and failed-attempt fencing; trusted-clock rejection;
schema-12 upgrade preserving source, metadata, audit and sync rows; migration
rollback; and missing/future schema rejection. Existing snapshot, retrieval,
processing, sync and core community tests remain regression coverage.
