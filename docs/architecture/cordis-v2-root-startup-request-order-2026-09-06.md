# Cordis V2 ROOT startup requested-before-apply

For a newly composed persistent ROOT candidate, startup now commits the requested distribution and its exact DesiredBundleSet source binding before invoking Host.apply. Preparation locks the ROOT scope head, verifies that desired still matches the loaded candidate and that its Bundle references match the verified archives, allocates the publication version and advances generation past any newer retained request. A failed preparation transaction cannot execute the candidate.

ROOT runtime generation and desired revision are independent counters. Publication-source record/read retain the existing equality constraint for non-ROOT scopes; ROOT instead keeps the immutable publication identity, strict scope and payload validation without requiring those two counters to coincide. No historical rows are guessed or rewritten.

Startup records the real Python receipt against the already persisted nonce through record_data_plane_receipt. A superseding request causes the stale receipt check to fail. The application host and route state are installed only after receipt persistence; any earlier error closes the uninstalled host. For deployments that do not require the Python plane, startup checks the latest nonce under the ledger lock before installation and does not manufacture a Python receipt.

## Limits and remaining work

This changes new ROOT startup candidates. The unchanged durable restore branch still needs exact historical-source recovery and final admission fencing, including newer unreceipted requests; it is not covered by a claim that all ROOT restart paths are complete. Marketplace mutation/publication still needs requested-before-apply ordering and pending-receipt admission control. Startup failures can leave an honest requested or ACK record when a database commit succeeds but its response fails; reconciliation/recovery of that state remains explicit work.

The startup fault tests use real SQL persistence and separate sessions, not PostgreSQL connection isolation. A PostgreSQL ROOT concurrency gate remains required. Full historical migrations, V1 retirement, other data-plane consumers, final parity rebinding and native acceptance remain open.

## Validation

- Existing ROOT configuration, cancellation and verified-byte startup: 8 passed, 95.28 seconds.
- Scoped publication source/recovery/coordinator plus ROOT source binding: 26 passed, 6.16 seconds. The separate 4-case ROOT binding run overlaps this result.
- Startup ordering/fault injection: 8 cases covered by the initial 5-case run (37.04 seconds) and a 4-case changed/additional run (28.12 seconds; one before-commit receipt case overlaps). Tests include requested commit before/after failure, receipt commit before/after failure, stale receipt after concurrent staging request, real desired CAS changes, empty archives and committed source visibility before route staging.
- Ruff, generation/completeness and Pyright passed; Pyright 0 errors/0 warnings.
- Logs and SHA256SUMS: `/var/tmp/cordis-root-request-tndvpr5u`.
- The cross-batch whole v2 unit run remains separate and is not an immutable final-revision gate.
