# Cordis V2 Host receipt admission gate — 2026-09-06

## Delivered behavior

`PlatformPluginRuntimeHostV2.apply` and `apply_distribution` accept an optional async receipt persister. When supplied, the host owns the publication task through caller cancellation, serializes apply and persistence, and exposes accepted publication/distribution metadata only after persistence succeeds. The callback must own its database session and must not reenter the host while its lock is held.

Persistence failure retains the actual ACK or NACK in `pending_receipt`. New `acquire` and ordinary apply calls reject with `publication_receipt_pending`. Existing leases may retain their exact admitted generation. A newly applied pending generation has no admitted distribution. Same-digest updates retain the previous distribution nonce until persistence succeeds.

`retry_pending_receipt` persists that same outcome without reapplying, then releases the admission gate. Closing clears the retained receipt. An unexpected staging failure before a receipt exists leaves admission closed; it does not fabricate a receipt. Calls without a persister retain their existing publication behavior.

## Validation

- New real Loader/verified archive fixture tests: **8 passed**, 0.36 seconds. Cases cover ACK/NACK persistence failure, old exact leases, new pending exact lease rejection, same-digest success and failed persistence, cancellation during apply/retry persistence, close, and distribution forwarding.
- Existing Host and publication/runtime cancellation suites: **38 passed**, 78.26 seconds.
- Host, verified archive, and initial five receipt tests: **44 passed**, 78.99 seconds. These overlap the runs above and are not additional unique coverage.
- Ruff and generated protocol/contract completeness checks pass.
- Focused production Pyright: **0 errors, 4 warnings**.
- Logs and SHA256 manifest: `/var/tmp/cordis-host-receipt-wvah7m3r`.

GitNexus reported apply HIGH (3 direct callers, 5 total), apply_distribution HIGH (1 direct, 3 total), class MEDIUM (12 direct, 71 total), acquire LOW, and close LOW after resolving its UID without the file filter. The index cannot establish complete current boundary coverage; manual inspection found new boundary admission uses acquire and detached retention uses acquire_exact.

## Remaining integration and limits

The new tests use persistence callback substitutes, not SQL transactions. Marketplace publication does not yet pass the callback. Its requested/source transaction must commit before apply, with receipt persistence using an independent session and recovery owned beyond the HTTP request lifetime. Route coordination must preserve the actually committed graph for persistence retry and reuse its existing graph on same-digest ACKs. A non-HTTP recovery path is needed while HTTP admission is closed.

The gate controls new operation admission, not staging-time resource startup. It does not establish continuous ROOT governance validation, historical source backfill, V1 retirement, or final native acceptance. Final fixed-revision full suites and parity/native gates remain outstanding.
