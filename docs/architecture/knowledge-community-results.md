# Audited local community results

B2a adds executable core/device contracts for semantic community results and
explicit active-build selection. B1 supplies immutable inputs and leased jobs.
Provider HTTP, sidecar execution and product entry points remain a subsequent
batch; this storage implementation alone is not the community product closure.

## Agent contract

`community::worker::request_community` calls the supplied `LlmPort` once with
`submit_knowledge_community`. Every name, summary and sufficiency decision comes
from that structured Agent output. A graph partition is only a structural
candidate. There is no text naming fallback or semantic identity merge.

`CommunityInput` binds the build ID, graph digest, candidate membership digest,
ordered entity references and immutable snapshot. Source payloads, metadata,
entity names and relationship facts are untrusted data. The Agent must echo
build/digest/candidate/members exactly. Evidence references must belong to the
candidate and its audited source revision/change sequence; a relationship must
connect two members of that candidate.

A `ready` decision contains a name, summary, rationale and nonempty evidence.
`insufficient_evidence` contains rationale and an evidence list, with no name or
summary fields. That outcome is durable terminal work, not a provider failure
and not a deterministic assessment of semantic quality.

Input serialization stops at 1 MiB, with at most 4096 members and 1024 sources.
Responses are parsed only below 2 MiB. Names, summaries and rationales are
limited to 256, 16384 and 4096 Unicode characters; evidence has at most 256
entries. Host identity fields are bounded. No contract carries credentials,
raw rejected Provider responses or raw Provider errors. Failure digests are
exactly 64 hexadecimal characters.

## Durable audit and publication

`begin_community_audit_durable` requires a current lease and exact persisted
input before recording Agent/provider/model/tool/contract identities and start
time. It checks that the frozen graph remains current before any provider call.
The caller performs provider work outside all repository locks.

`finish_community_audit_durable` returns the actual durable audit record. An
`Ok` return does not imply applied output: an expired/reclaimed lease records
`LeaseLost`, and a changed graph records `GraphChanged`. These reject publication.
A failure can terminate only its own attempt's audit; it cannot mutate a
replacement worker's job. Completion validates the stored lease deadline,
worker, token, attempt and exact immutable input, then re-captures the graph
inside the write transaction. Results, terminal audit and completed job are
committed together after the final clock/admission callback succeeds.

Graph changes include metadata edits, deletions and late extraction completion
without a source revision change. A stale build needs a new build; a retry does
not replace its frozen input. Rejected valid submissions retain a domain-bound
SHA-256 digest of the structured terminal request. The separate request digest
also permits identical replay after an Applied request was converted into a
rejection. A different request conflicts. Accepted terminal replay returns the
original result without requiring its now-expired lease to become live again.

Terminal audits and results reject updates and deletion. Audit inputs cannot
be changed even while the attempt is pending. Historical result reads validate
the submission against immutable input and the matching Applied audit.

## Active build selection

Build status is derived from durable jobs and results. The B1 creation receipt
remains immutable, avoiding a second mutable set of completion counters.
`select_community_build_durable` updates the requested build with a selection
revision CAS, preserving the previous active build. A worker must retain that
revision for its later activation attempt.

`activate_community_build_durable` accepts only that requested build/revision,
a current graph and a wholly completed candidate set. Partial/failed builds
return false; a stale selection or graph conflicts. Old workers cannot replace
a newer selection. Zero candidates can activate as `completed_empty`; an
all-insufficient build exposes its counts without invented names.

`active_community_build_durable` returns current output only when its graph is
still current in the read transaction. Otherwise it returns the stale build ID
and no current results. Explicit historical result reads retain prior output.
Sidecar callers must perform their existing final authorization/generation
checks before delivery and must not promote a historical read to live status.

## Schema and sidecar integration

Schema 14 rebuilds the community job state constraint to include completed,
preserves existing jobs/leases/attempts and adds audit, result and selection
tables. Version advance and all DDL/data copying share the existing migration
transaction. Missing current objects and future versions fail closed. Native
activation must use the existing online-backup lifecycle before migration.
Tests that deliberately restore an old schema remove the new result tables;
those fixtures are not a supported application rollback mechanism.

The next sidecar worker reuses verified processing Provider resolution,
`MeteredLlm`, authorization/generation admission, periodic lease renewal and
cancellation handling. It calls the device clock-callback methods, inspects the
returned audit outcome and attempts revision-fenced activation only after
completion. The core worker and device repository perform no Provider HTTP or
renderer work themselves.
