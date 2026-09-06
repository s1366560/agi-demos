# Cordis V2 PostgreSQL scoped restart acceptance

The scoped restore concurrency gate passes on an isolated PostgreSQL 16 container. The reproducible runner `scripts/verify_scoped_restart_postgres.py` applies the seven ledger migration upgrades from `dc206dd13ac3` through `d72e6b8f0a41`, runs four integration files, and removes its owned container in a finally block. Credentials remain in process memory and child environment.

## Verified behavior

- An independent coordinator restores the exact ACK snapshot and envelope without adding publication or receipt history.
- While restore staging holds PostgreSQL connection A, another coordinator commits a newer request and its ACK on connection B. Backend process IDs prove separate connections. The final restore fence rejects the stale state, admission remains unavailable, and shutdown disposes the staged runtime once.
- A newer unreceipted request prevents restoring the older ACK without applying runtime changes or adding history.
- Existing publication transaction, multi-process supersession, scoped ledger and profile fence cases pass alongside the three new cases.

## Evidence and limits

Command: `PYTHONPATH=. uv run python scripts/verify_scoped_restart_postgres.py`.

Result: **14 passed, 21 warnings, 13.08 seconds**, no skipped tests. Owned container cleanup exit 0. Runner Pyright: 0 errors, 0 warnings. Ruff passed for both new Python files. Logs and SHA256SUMS: `/var/tmp/cordis-scoped-restore-pg-jwj1yq9y`.

This closes the PostgreSQL restore-versus-publication concurrency gate listed in the preceding scoped restart report. It verifies a ledger migration slice, not the complete historical Alembic chain or a business database conversion. Historical unbound publication recovery, ROOT lineage, broader actor/worker coverage, final V1 retirement, parity rebinding and native acceptance remain open.
