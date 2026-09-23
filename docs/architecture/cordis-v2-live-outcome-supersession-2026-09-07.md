# Cordis V2 live outcome supersession — 2026-09-07

## Delivered behavior

The Host and HTTP route coordinator now expose an owned, explicit replacement operation for an exact pending publication. It requires a strictly higher requested version, commits the old real outcome's audit before applying the candidate, retains the pending object on audit failure and keeps new admission closed throughout. Waiter cancellation does not cancel audit/apply/receipt work, and close waits for the Host lock. Existing exact generation leases remain valid.

A replacement ACK updates the durable Host mapping only after its receipt and route commit callback complete. A failed ACK receipt can be retried without reapplying or restaging the graph. A replacement NACK sets the typed pending_requires_ack flag before its persister runs and remains fenced even if the receipt committed. Receipt-only retry rejects this mode before invoking its persister. A later, higher ACK is required to release admission.

This NACK rule covers both SQL states: if the old local ACK was never persisted, a NACK referring to it is rejected by the real ledger as last_good_mismatch; if that ACK committed but its response was lost, the new NACK can be durable while the Host mapping still names an older publication. Neither outcome is a reason to open admission with mismatched metadata.

Background recovery now checks for a newer unreceipted request before receipt retry. It uses the existing verified source/archive recomposition, the route coordinator and a separately committed outcome supersession audit. With no newer request, a replacement NACK returns no work without another apply or persistence attempt. Unbound requests remain rejected. If a third request arrives during staging, the intermediate actual result remains pending and is audited before the later request is applied.

## Validation

- Host replacement: 11 tests passed in 0.42 seconds, covering old ACK/NACK, identity/version checks, audit faults, receipt retry, cancellation, close and old leases.
- Route replacement: 6 tests passed in 100.50 seconds, covering graph/callback ownership, NACK retention, audit failure, receipt-only retry, locked authority checks and foreground competition.
- Existing route/Host plus new Host regression: 26 passed in 82.79 seconds. This overlaps the Host cases above.
- Real SQL recovery: six cases passed in 163.32 seconds, plus the staging competition case passed in 36.71 seconds. Cases cover audit commit before/after errors, the two durable-state NACK branches, idempotent waiting, higher ACK recovery and unbound source rejection.
- Existing market regression: final 16 passed in 257.61 seconds. The initial run had 15 passes and the old stale-error assertion failed because recovery now rejects the newer unbound request first. That test now expects root_receipt_pending and also asserts zero audit rows.
- The initial SQL NACK assertion expected receipt_invalid; it was corrected to the existing ledger's precise last_good_mismatch error. No ledger acceptance rule was weakened.
- The expanded PostgreSQL gate passed 35 tests in 425.75 seconds, with no skips; the subsequently added staging competition passed separately in 36.20 seconds. Both owned containers were removed with exit 0. The runner now collects 36 cases. Durable logs and SHA256 manifest: /var/tmp/cordis-live-supersession-7rx93ca0. The additional staging wrapper initially passed an extra test-helper argument; that adapter-only TypeError was corrected before its final run.
- Ruff, generated protocol and contract completeness pass. Focused route/recovery Pyright has no errors/warnings; Host Pyright has zero errors and four existing warnings. Direct review covers all new calls.

## Remaining release gates

Recovery of a newer already-receipted publication on a stale local Host is not added here; the existing verifier still distinguishes unreceipted recovery from durable restore. The approved Stage 7 administrator republish endpoint also needs to update desired/source authority and use the verified route coordinator rather than its current direct Host call. This is an identified production integration gap, not a reason to relax source fencing.

After that approved rollback path is closed, final acceptance must use a frozen commit: complete V2 composition and cross-language suites, full product profile readiness, current Web/Desktop parity, real native Provider operation and V1 retirement backup/export/conversion evidence. V1 tombstone and migration implementations already exist; their final operational proof remains outstanding.
