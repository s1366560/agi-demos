# Cordis V2 marketplace PostgreSQL acceptance — 2026-09-06

## Scope

The owned PostgreSQL runner includes the real marketplace publisher in addition to scoped recovery and ROOT startup gates. Each new case uses a separate UUID schema, applies the seven ledger/source revisions through d72e6b8f0a41, and drops its schema afterward. This is a migration-slice test, not proof of the complete historical Alembic chain.

The market publisher starts from a real persisted ROOT startup, resolves the production bundle archive, and uses the real route coordinator, Loader and receipt repository. No external artifact fetch is needed for this builtin profile.

## Assertions

1. The mutation session has ended its publication transaction when staging starts. It then checks out connection A and keeps it occupied while connection B reads the exact requested nonce and immutable source binding. Backend PIDs differ, and only the preceding startup receipt exists. The receipt writer also uses a different backend from held A.
2. A receipt session commits successfully and then raises OSError. The actual ACK remains pending, the previous admitted publication remains, and new admission rejects. Retrying with the real persistence helper keeps the same runtime and route objects, performs no second staging, and adds no duplicate receipt event.
3. Connection B commits a higher-version requested distribution while the candidate stages. The actual local ACK is rejected as stale at persistence, leaves the prior durable receipt history unchanged, and keeps Host admission blocked. No NACK is fabricated.

## Results

- Owned runner: **20 passed**, 21 warnings, 93.42 seconds, no skips. Includes three new marketplace cases and seventeen prior scoped/ROOT cases.
- Owned container cleanup exited 0.
- Ruff, diff check and runner Pyright pass; Pyright reports zero errors and warnings.
- Evidence logs and SHA256 manifest: `/var/tmp/cordis-market-postgres-c2e90589`.
- Manual review confirms the only runner behavior change is adding this test module; container ownership, environment-only credentials and cleanup remain intact.

## Remaining work

Recovery outside blocked HTTP admission is still required, including reconciliation when a pending actual receipt is superseded. This gate does not validate marketplace OCI permissions or non-builtin network retrieval, historical migration/lineage backfill, final V1 retirement, full fixed-revision suites, parity rebinding, or native acceptance.
