# Cordis V2 marketplace receipt recovery — 2026-09-06

## Delivered behavior

The production application lifespan starts `MarketplaceReceiptRecoveryV2` alongside the publication deadline reconciler. It polls for an actual retained Host receipt without acquiring a data-plane lease, so HTTP admission fencing cannot prevent recovery. With no pending receipt it performs no database work. Persistence uses the existing real receipt helper and fresh sessions; it never applies a candidate or fabricates an outcome.

Transient persistence and callback failures leave the actual pending outcome intact and permit a later polling attempt. A persister raising CancelledError does not kill the loop unless the loop itself was cancelled. A stale receipt remains rejected by the repository and admission stays closed. A foreground publication completing while recovery waits is handled as no remaining work.

Shutdown stops this task before closing the Host. Stop wakes the polling wait and drains any in-flight coordinator persistence; cancellation of a stop waiter does not cancel the owned drain or database operation. The default polling interval is five seconds and must be finite and positive.

## Validation

- Real startup/SQL recovery tests cover no pending work, successful real helper retry, ordinary and cancellation failures followed by background recovery, stale receipt rejection without history change, held-commit stop, cancelled stop waiter, and real runtime shutdown ordering.
- Initial five recovery cases passed in 75.59 seconds. The loop case was extended to OSError and CancelledError, and those two cases passed in 31.48 seconds (four unchanged cases are covered by the first run). Six unique cases total.
- Five actual main lifespan cases passed in 2.04 seconds with receipt task startup included in the ordering assertion.
- Initial broader lifecycle run had 13 passes and one legacy assertion failure: a local restore NACK was expected to overwrite the original durable ACK. Current `restore_root_startup_v2` rejects that local outcome without writing history. The test now checks unchanged requested distribution, one original ACK event and no installed failed Host; production restore behavior was not altered.
- Production Pyright: zero errors, two existing unused-call-result warnings in main.py. Ruff and generated protocol/contract completeness checks pass.

- Final complete lifecycle/startup/cancellation group: **14 passed** in 83.98 seconds, including the five lifespan cases above.
- Logs and SHA256 manifest: `/var/tmp/cordis-receipt-recovery-54vufpnl`.

## Remaining gates

Recovery of a superseded pending outcome, a committed request with no actual receipt, and restart reconstruction still require coordinated candidate recovery. This task only retries the actual retained receipt; stale authority is never bypassed. PostgreSQL coverage of the background recovery lifecycle, continuous ROOT governance fencing, historical source migration, final V1 retirement, final full suites, parity rebinding and native acceptance remain outstanding.
