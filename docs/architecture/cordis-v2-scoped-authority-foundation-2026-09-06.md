# Scoped authority foundation

Marketplace installation and uninstallation currently mutate the ROOT desired set and publish
to the process-wide host. Commit `e131eb53f` requires platform administrator authority for those
operations, matching package revocation. Tenant administrators can still approve permissions for
their own tenant. This closes the confirmed tenant-admin-to-root mutation path; it does not
implement tenant-scoped installation. Seven real signed-package router tests pass, including
successful publication, idempotency, NACK last-good retention, uninstall, and rejected tenant
mutations without state writes.

`ScopedRuntimeRegistryV2` now provides the in-process foundation for distinct Python authorities.
Each validated full scope gets its own Loader, Reconciler, GenerationManager and publication
lock. An entry must belong to that exact scope or an ancestor; lookup never falls back to an
ancestor's host. Python modules declaring global route-table or route-authority services are
rejected before apply. Callers supply definitions and own authentication and durable versions.

Closing detaches and marks a slot retired before draining it. An in-flight candidate checks
retirement again before commit, so it cannot republish into the retired slot. A subsequent
explicit publish may create a new slot. Caller cancellation does not cancel owned cleanup;
pending cleanup drains before aggregate failure is reported. Completed successful retirements
release host references. Completed failures remain observable through repeated global close;
a later close_scope with no pending work does not replay historical failures. Existing leases
retain their generation until release, which observes any late disposal error.

Validation: 15 real Loader registry tests plus 26 layer-composer tests passed in the main checkout.
They cover full scope isolation, ancestor entries, sibling rejection, NACK retention, retired
publication fencing, lease draining, cancellation, multiple cleanup failures, and weak-reference
collection after repeated retirement. Log: `/tmp/cordis-scoped-runtime-main.log`.

At feature revision `371a7afb6`, the full Desktop suite passed with 4131 passed, 2 skipped and
0 failed in 94.74 seconds; 20 Web public-view/identity/lease regressions also passed. Evidence
files and their SHA256 inventory are retained under `/var/tmp/cordis-scope-foundation-smyvrbi0`.
The earlier Python full run had one route-inventory fixture failure, corrected and verified by
eight focused tests; a full rerun after that correction is not claimed here.

## Separate contract gate repair

Commit `667452b4f` gives each Rust Server worker an explicit module entry and service declaration.
The three worker contracts and lifecycle behavior remain unchanged. The generated catalog changes
only their entrypoints and source hashes. All 607 Rust Server tests passed on the exact applied
candidate; main-checkout generation and completeness checks pass. Logs:
`/tmp/cordis-worker-contract-server-full.log` and
`/tmp/cordis-worker-contract-main-completeness.log`.

## Remaining integration

The registry is not yet wired into HTTP requests or Agent turns. Publication and receipt storage now have scope-bound identities and transaction-safe
version allocation in `9354abeaf`; production membership
authorization and exact ProfileSource loading must be connected before non-root publication is
enabled. The Web public view remains root-only. These changes do not prove Stage 6 completion,
full native acceptance, or final V1 retirement.
