# Cordis V2 marketplace request before apply — 2026-09-06

## Delivered behavior

Marketplace publication now allocates its ROOT version while holding the ledger scope head, verifies the current desired revision and exact archive references, and records requested distribution plus immutable publication-source binding in the marketplace mutation session. That transaction commits before any candidate is staged. A commit error or cancellation does not apply the candidate, including an error reported after the database has committed.

The route coordinator receives a receipt persister using a separately owned session factory. It writes the real ACK/NACK only for the already committed nonce and inherits stale-request checks from the repository. It does not recreate the requested publication. For policies not requiring the Python plane, it checks the latest nonce without fabricating a Python receipt. The HTTP entry requires an AsyncEngine so receipt persistence cannot reuse a request-owned connection.

Persistence and graph notification complete under the existing Host admission gate. A failed receipt retains the actual local outcome and blocks new admission. The shared receipt helper can be used with route coordinator retry without applying the candidate again. The caller's request session and HTTP artifact client are not used by receipt persistence after cancellation.

## Validation

- Marketplace route and audit suites: 14 passed in 24.76 seconds.
- Production Ruff and Pyright: pass, 0 type errors and 0 warnings.
- Generated protocol and contract completeness checks pass.

- Initial service/source/archive/transaction run: 17 passed in 81.87 seconds (includes the initial two transaction cases).
- Expanded transaction faults: 5 passed in 64.08 seconds, covering successful receipt, receipt before/after commit errors with actual helper retry, and requested before/after commit errors with zero apply.
- Three receipt/order cases rerun after adding the structural assertion that the mutation session is no longer in a transaction at staging: 3 passed in 44.95 seconds. This overlaps the five-case run.
- Receipt-after-commit retry preserves one runtime/route application and exactly one added receipt event.
- Logs and SHA256 manifest: `/var/tmp/cordis-market-durable-k71xipr3`.
- Manually checked all four service construction sites.

## Remaining gates

A receipt retry callable is available, but automatic recovery outside blocked HTTP admission is not yet installed. A committed requested row with no actual receipt after request-commit failure requires explicit recovery of that recorded candidate; no receipt is guessed. PostgreSQL race coverage for the running marketplace path, continuous ROOT governance fencing, historical lineage migration, V1 retirement, final fixed-revision full suites, parity rebinding and native acceptance remain outstanding.
