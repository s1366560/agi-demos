# Cordis V2 marketplace verified execution

ROOT marketplace publication now retains each verified archive through composition and passes the complete candidate archives through HTTP route publication to Host.apply. The route coordinator freezes that sequence before waiting for its lock. The Loader executes the byte attestation introduced for ROOT startup; archive manifests alone no longer stand in for execution evidence on this path.

A real persistent ROOT regression uses the application route coordinator and SQL publication repositories. It publishes a valid candidate, injects corruption after archive verification while keeping the manifest unchanged, checks NACK and retention of the exact prior host generation and route publication, and then successfully publishes another valid candidate. The rejected candidate does not call the route commit callback; its publication is retained while durable last-good remains unchanged. This test uses the trusted builtin production archive and no external artifact fetch; signed archive and dynamic load identity coverage is recorded in the preceding ROOT execution report.

## Remaining transaction work

This change does not reorder durability. The marketplace mutation router still calls republish before its database commit. The publisher applies routes/runtime before recording its publication and receipt. ROOT startup has the same apply-before-ledger ordering. Exact publication-source binding must be captured with the requested publication before apply, with a post-staging admission fence. It must account for independently increasing runtime generations versus desired revisions and preserve the documented persistence of control-plane mutations on local NACK. A commit failure after runtime activation remains an open acceptance case.

Historical ROOT migration and source binding, complete historical Alembic verification, other data-plane consumers, final V1 retirement, parity rebinding and native acceptance remain open.

## Validation

- Marketplace install/source/router and route publication regressions: 44 passed, 21 warnings, 320.09 seconds.
- Real ROOT marketplace corruption/recovery test: 1 passed, 22.90 seconds.
- Pyright: 0 errors/0 warnings. Ruff and protocol generation/completeness checks passed.
- Logs and SHA256SUMS: `/var/tmp/cordis-marketplace-archives-65bko4zd`.
- The earlier full v2 unit baseline remains a separate ongoing run and is not included as a completed gate.
