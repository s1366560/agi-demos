# Cordis V2 marketplace atomic source fence — 2026-09-06

## Delivered behavior

Marketplace receipt persistence now locks the ROOT ScopeHead in its own receipt transaction before reading the exact requested publication, its immutable desired-source binding and current desired state. It requires the stored required-plane roster to match the active policy and compares the complete desired state with the binding. Only then does it call the existing actual receipt writer and commit.

Desired compare-and-swap already acquires the same head before its desired row. Receipt persistence acquires the head before publication/apply-state rows, so the final source check and receipt commit are serialized with desired mutation without reversing lock order. Archive loading and network operations remain outside this transaction.

The shared helper covers foreground marketplace publication, background live recovery and actual pending receipt retries. An existing durable receipt does not bypass the source check on retry. Missing bindings are rejected as root_publication_source_missing; changed desired state as root_recovery_changed; changed required-plane policy as root_recovery_policy_changed. The generic external receipt repository retains its existing protocol behavior.

## Validation

Five new PostgreSQL cases cover desired commit after the earlier standalone precheck, receipt holding the scope lock while desired CAS waits, already-durable ACK retry after desired changes, missing binding and policy changes. The lock test uses distinct backend PIDs and pg_blocking_pids to verify the actual wait relationship. Its observation while the lock is held uses only ordinary count queries; full recovery repository reads occur after release.

The full expanded PostgreSQL runner passed 27 tests in 235.13 seconds, with no skips and owned container cleanup exit 0. Marketplace publication/live/receipt regression passed 16 tests in 249.44 seconds. Ruff, generated protocol, contract completeness and focused Pyright pass; Pyright reports zero errors and warnings. Evidence logs and SHA256 manifest: /var/tmp/cordis-atomic-source-le2muy1b. Direct review found the three production callers and verified the shared head-first lock ordering.

## Remaining boundaries

This is transaction-boundary source fencing. A later desired mutation can still require separate continuous admission reconciliation. Superseding an actual stale pending outcome remains unresolved. Historical lineage migration, the full historical Alembic chain, V1 retirement, final full suites, parity rebinding and native acceptance remain outstanding.
