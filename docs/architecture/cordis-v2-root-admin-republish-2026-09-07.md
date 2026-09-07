# Cordis V2 explicit ROOT administrator rollback — 2026-09-07

## Behavior

The administrator republish endpoint now restores the last globally-ready ROOT configuration through the verified route publication coordinator. It no longer calls the Host directly or writes a local receipt through the request session.

The new rollback repository locks the existing ROOT scope head, validates the stored ready distribution and its exact source binding, and appends a new desired revision with the administrator's actor ID. It preserves the old configuration content but allocates a generation above every ROOT requested generation and a new publication version. The new request, source binding and republished-from audit link are written in the same caller-owned transaction. Missing ready/source data and corrupted stored identity are rejected before configuration mutation. A transaction rollback also rolls back the version allocation.

Fresh generation identity matters when Python has already activated B while another required plane NACKs: an old A lease can still retain A's route table. Reusing A's original descriptor would collide with that retained table. The new A publication has a distinct descriptor while preserving the old lease and its resources.

After committing the request, the existing ROOT recovery path loads verified archives, recomposes the exact snapshot, checks current desired/source authority and stages the real route graph. Its independent receipt transaction retains all existing source, roster and publication fences. An explicit nonce fence prevents the foreground administrator call from applying a different newer request. If an actual pending outcome exists, the existing audited supersession operation owns its replacement. New admission still waits for durable receipt completion.

The generic ledger's historical republish helper remains available for ledger-level callers and tests; production has no caller of that method after this change. The administrator endpoint requires a bound source and a real local route coordinator when Python belongs to the required roster. Ephemeral clients are not silently added to the roster.

## Validation

- Repository: four focused tests passed, including original history retention, actor/source binding, new counters, caller rollback and corrupt identity rejection.
- Real local chain: A ready, B desired with a real archive-verification NACK, administrator POST, route ACK, shutdown and exact restart; no extra request or receipt is created on restart.
- Retained lease chain: Python activates B while an independent Host used as a protocol-plane fixture NACKs; administrator rollback creates a fresh A generation while the original A lease remains usable. This fixture is not Rust or Desktop acceptance.
- The first combined run had three passes and one test-only missing descriptor argument. The retained-lease test passed after correcting that argument; no production acceptance rule changed.
- Two old router fixtures with unbound publications now assert HTTP 409 and unchanged publication/runtime identity.
- Nonce fence: one test passed, proving a different pending request is untouched and its exact nonce can subsequently recover it.
- Existing live requested recovery: five tests passed in 93.24 seconds.
- Complete router regression: 25 tests passed in 51.24 seconds.
- Independently migrated PostgreSQL regression: all 38 cases passed in 529.93 seconds, with no skips. This includes both real admin rollback chains; the owned container was removed with exit 0.
- Ruff, protocol generation and contract completeness passed. Focused production Pyright reported zero errors and one existing router warning. GitNexus returned LOW for the indexed endpoint; newer helpers remain unindexed and shifted symbol locations limit its scope report, so direct source review covered the new transaction and coordinator calls. Staged secret scanning found no leaks.
- Durable local logs and SHA256 manifest: `/var/tmp/cordis-root-rollback-t_r1d0pd`. The directory is private and contains the initial test-only failure as well as terminal passing results.

## Release boundary

This batch closes the explicit administrator republish integration gap identified in the live outcome supersession report. Final release remains subject to a frozen-commit Python/Rust/Desktop run, full product composition and actual required-plane readiness, current parity, real native provider acceptance, and the V1 backup/export/conversion/restore evidence. The existing independently migrated PostgreSQL runner proves its eight-revision ledger slice, not the entire historical database migration chain.
