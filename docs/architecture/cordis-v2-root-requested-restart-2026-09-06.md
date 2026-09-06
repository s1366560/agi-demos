# Cordis V2 exact requested restart recovery — 2026-09-06

## Delivered behavior

Persistent Python-required ROOT startup now checks for a committed latest request with no actual receipt before configuration initialization or normal last-good restore. It requires an exact publication-source binding equal to current desired state and an unchanged required-plane roster. It loads the exact stored ProfileSource (or its exact builtin baseline identity), re-verifies archive bytes and recomposes the complete snapshot at the recorded generation. The recomposed snapshot must equal the requested snapshot.

Recovery reads and compares durable state before loading, immediately before staging and after actual apply. During rechecks it compares captured requested/last-good/receipt state before validating the potentially new request's source, so a competing publication is reported as root_recovery_changed. It applies the original nonce, version and generation without allocating or inserting another request. The existing initializer persists the real result and installs the Host only after receipt commit; failure closes the candidate Host.

An unbound pending request remains root_receipt_pending. A changed desired set, required-plane policy or incompatible snapshot is rejected. Existing receipted restore and policies not requiring Python retain their previous paths. This does not guess receipts or apply startup activation overlays to the recorded request.

## Validation

- Five new real SQL/Loader cases pass: first-start requested commit followed by error then same-request restart; marketplace requested commit error after an old ACK then same-request restart; concurrent new request during staging; valid snapshot incompatible with its bound source; changed restart required-plane policy.
- Full five-case run: 5 passed in 65.32 seconds. The policy case was then changed to pass a different restart policy without altering the immutable requested row and passed individually in 9.89 seconds.
- Existing request-order and restore-fence suites: 15 passed in 182.04 seconds.
- Initial new run: 3 passed, one error-code assertion failed because an unbound competing request was validated before comparing the captured state. The read ordering was corrected and the full new run passed. Background fixture logs about unavailable default PostgreSQL were not the assertion failure.
- Ruff, generated protocol/contract completeness and focused Pyright pass; Pyright reports zero errors/warnings.
- Evidence logs and SHA256 manifest: `/var/tmp/cordis-root-requested-1b45hy6k`.
- GitNexus did not index the recent startup helper symbols. Direct review covered the single persistent startup caller, pre/post state checks and unchanged final receipt/install transaction.

## Remaining work

This implements restart recovery, not live replacement of an already blocked Host. Coordinating unreceipted/superseded requests without restarting, PostgreSQL coverage of this new recovery branch, continuous governance admission, historical lineage migration, final V1 retirement, full fixed-revision suites, parity rebinding and native acceptance remain outstanding.
