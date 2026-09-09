# Native portable project-schema storage

This module is a storage foundation. Knowledge schema version 15 adds an empty
project-schema head table and an immutable acceptance journal. Existing Memory,
processing, community, and synchronization data stay in their existing tables.
The desktop storage lifecycle takes its normal pre-upgrade SQLite backup before
the migration. Opening storage does not create a project schema.

Callers explicitly supply tenant/project scope, actor, canonical UUID change ID,
expected revision, and a document validated by `agistack_core::project_schema`.
Bootstrap accepts revision 1 against expected revision 0. Whole-document replace
requires an adjacent revision, stable schema/member identity, retained tombstones,
and a live previous head. Terminal deletion retains the final head and history.

Mutations acquire an SQLite IMMEDIATE transaction. Exact actor/change-ID replay
is checked before CAS and returns the original persisted receipt even after later
updates or deletion. Reusing the ID with a different submitted command fails.
Accepted member arrays are sorted by ID; original submitted array order remains
part of command identity. Opaque values use the existing core parser/serializer.
Names are not deduplicated or interpreted as semantic identity.

Every operation requires a host-supplied `current` callback after transaction
acquisition and immediately before commit, including replay and pure reads. A
failed callback rolls back transaction work. It must not reenter the repository.
The callback is an integration fence; these storage methods do not authenticate
the actor or authorize a scope. No permissive production callback is installed.

Reads never bootstrap defaults. History pages contain at most 100 immutable
receipts and expose the head revision observed in the same read transaction.
A cursor beyond that head fails. Persisted receipts and heads are validated
before use; SQLite guards prevent ordinary SQL updates/deletes of the journal,
unjournaled head changes, identity changes, and nonadjacent append operations.

There is no API or capability registration, default activation, sync association,
transport outbox, scheduler, cloud dispatch, or automatic/semantic merge here.
The local journal is durable history only and is not evidence of synchronization.

Knowledge schema version 16 adds durable schema synchronization state under the
existing Memory sync binding: an epoch-fenced cursor, immutable prepared
transfer intent (at most one pending step), and immutable acceptance anchors
mapping native and cloud receipt revisions. SQLite triggers require the Memory
link/target association, chain every cursor advance to exactly one new anchor,
and reject any direct cursor, intent or anchor mutation. Pull initialization
and apply verify every presented cloud receipt through the pure cross-scope
projection (`agistack_core::project_schema::projection`) before any local
acceptance; bootstrap never overwrites a divergent non-empty native scope, an
accepted empty native seed receives the source root as the next revision, and
already equivalent heads bind without a write. A moved local head conflicts and
is never rebased. Cloud-bound steps persist their exact request bytes so an
uncertain remote outcome can be recovered by explicit receipt lookup. Native
intent, acceptance, anchor and cursor advance commit in one transaction.

The sidecar now has a dormant internal `ProjectSchemaOperationV2` wrapper. Its
admission checks the live local session, workspace context and exact project
generation before opening storage. Each operation repeats live read/write role
checks and supplies the real session-deadline callback under the existing
auth-to-generation-to-storage lock order. Actor and scope come from the admitted
session; write replay still requires current write permission. Schema errors
remain typed internally. No Memory command, public capability, route or RPC
calls this wrapper; connecting that surface is a separate implementation step.
