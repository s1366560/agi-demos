# Cordis V2 outcome supersession audit — 2026-09-06

## Delivered persistence boundary

The new outcome supersession repository preserves a real local ACK/NACK before a newer request replaces a blocked attempt. It records the exact scope, data plane, prior requested publication, replacement publication and complete actual receipt. The composite primary key makes a same-pair retry idempotent; a different valid receipt for that pair is rejected. Both publication references use scope-qualified foreign keys and RESTRICT deletion.

The caller owns the transaction. Under the ScopeHead lock, record validates both full distribution identities, data-plane membership, strictly newer and latest replacement, exact replacement source binding against current desired state, and the receipt's wire shape and requested identity. Any applied identity must refer to a requested publication in the same scope; it need not be the durable last-good because a superseded local ACK may never have reached the receipt ledger.

Recording audit evidence does not allocate a requested version, write an ACK/NACK event, update apply state, change publication readiness or open Host admission. The model is registered separately from the main persistence model file.

## Migration and validation

Migration e83f7c901b52 was generated with Alembic produce_migrations/render_python_code against an owned PostgreSQL instance at parent d72e6b8f0a41, then reviewed as one new table. The isolated check verified scope-qualified foreign keys for both identities, distinct requested identities, nonempty plane, parent RESTRICT, upgrade/downgrade/re-upgrade and metadata parity. Existing publications survived downgrade. The owned container was removed successfully.

The thirteen new unit cases include actual signed Loader ACK/NACK, idempotence, conflict, unknown applied identity and invalid scope/plane/request/version/source relationships. The combined desired/source/audit regression passed 21 tests in 4.40 seconds. The first exploratory conflict test used an invalid ACK error payload and correctly hit receipt validation; it was corrected to compare two valid NACK payloads before the final runs.

The expanded nine-file PostgreSQL runner passed all 29 tests in 256.07 seconds with no skips; the owned container cleanup exited 0. Its new two cases retain actual Host pending ACK/NACK and confirm audit idempotence, unchanged authority and closed admission. Durable logs and SHA256 manifest: /var/tmp/cordis-outcome-audit-7e5veibk. Ruff, generated protocol, contract completeness and focused Pyright pass, with zero Pyright errors/warnings. Alembic reports the single head e83f7c901b52. Direct review checked metadata registration, the sole runner entry and storage-only behavior.

## Next runtime work and remaining acceptance

The journal is a prerequisite; the live Host/coordinator does not yet call it. The controlled replacement operation must hold coordinator then Host locks, preserve the exact pending object until audit commit, keep admission closed throughout staging and persist the new actual receipt before releasing admission. A replacement NACK must remain blocked: its applied identity can refer to an earlier unreceipted local ACK, and even a durable NACK can leave Host distribution metadata behind durable SQL state. A successful replacement ACK is required to complete that transition.

Cancellation must drain the owned operation; old exact leases must remain valid; audit commit before/after errors and a third competing request need runtime tests. The expanded migration runner proves a ledger slice, not the full historical Alembic chain. Continuous governance admission, historical lineage migration, V1 retirement, final full suites, parity rebinding and native acceptance remain outstanding.
