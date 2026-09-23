# Cordis V2 route receipt recovery — 2026-09-06

## Delivered behavior

The HTTP route coordinator now retains the graph actually activated with the runtime generation. Startup supplies its exact graph. Same-digest ACKs reuse that graph after verifying the current runtime descriptor, registry descriptor, and table identity; they no longer require a stager call that the reconciler deliberately skips.

`publish_snapshot` can accept a receipt persister. The coordinator owns publication through cancellation and forwards persistence through the Host admission gate. The actual ACK/NACK and route companion survive persistence failure. NACK outcomes have no accepted route companion and preserve the previous graph. `retry_pending_receipt` requires the same retained Host receipt, revalidates the accepted graph, and retries persistence without staging or activating routes again.

The synchronous `on_commit` callback runs after persistence but before Host admission reopens. If it fails, the already durable ACK remains an ACK and the committed routes remain active; the error and pending outcome are retained for retry. Both persistence and notification callbacks must be idempotent or otherwise safe to retry, own their required resources, and never reenter the coordinator or Host. The production notification assigns the app route graph.

## Validation

- New real startup/Loader route tests: 7 passed in 84.81 seconds. Covers same-digest reuse, ACK/NACK failed persistence and retry, caller cancellation, retryable notification failure, table mismatch before persistence, and a persister raising CancelledError.
- Initial five tests ran before the new API was loaded and failed with unexpected receipt_persister keyword; retained as the red run, not a product regression.
- Focused production Pyright: 0 errors, 0 warnings.
- Ruff, generated protocol and contract completeness checks pass.

- Existing route publication suite: 23 passed in 266.05 seconds.
- Existing real SQL marketplace archive execution regression: 1 passed in 23.10 seconds.
- Logs and SHA256 manifest: `/var/tmp/cordis-route-receipt-pqcqdjpz`.
- Source review covered the retry method's Host receipt identity, route identity and callback order.

## Remaining work

Receipt callbacks in the new tests are substitutes, not SQL durability proof. Marketplace still calls the old apply-before-commit service path. Its mutation/requested/source transaction must commit before apply, receipt persistence must use an independent session, and retry must be reachable outside the blocked HTTP admission path. These changes remain necessary before declaring running ROOT publication durable.

This batch does not complete historical source migration, continuous governance admission, final V1 retirement, full fixed-revision suites, parity rebinding, or native acceptance.
