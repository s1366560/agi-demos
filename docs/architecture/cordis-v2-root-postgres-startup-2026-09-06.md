# Cordis V2 ROOT PostgreSQL startup acceptance

The owned PostgreSQL runner now includes ROOT startup acceptance alongside the scoped restart/publication tests. ROOT cases use a new UUID schema for each test, apply the real seven-revision ledger migration slice through `d72e6b8f0a41`, and remove that owned schema in cleanup. The runner removes its owned container in its finally block.

## Gate scope

The ROOT gate checks that requested publication and source binding are visible on a separate connection before route staging completes; that a newer request committed while an exact restore is staging blocks final installation; and that supersession before receipt persistence rejects the old startup admission. Held PostgreSQL sessions and backend process IDs distinguish actual connections.

This is a ledger-slice and startup concurrency gate. It does not verify the full historical Alembic chain, business-data migration, marketplace transaction admission, V1 retirement, or final native/parity acceptance.

## Validation

Command: `PYTHONPATH=. uv run python scripts/verify_scoped_restart_postgres.py`.

Final result: **17 passed, 21 warnings, 48.84 seconds**, no skipped tests; owned container cleanup exit 0. All three ROOT cases passed alongside the existing 14 scoped ledger/publication/recovery cases. Production code remained at `3eb311dcc` during this acceptance batch. Ruff passed; runner Pyright reports 0 errors/0 warnings. Alembic reports the single head `d72e6b8f0a41`; this does not imply full-chain acceptance.

The first attempt exposed a test fixture loop mismatch (asyncpg connection initialized on the default session fixture loop, then reused on a function test loop). The fixture now explicitly uses the function loop, with bounded database statement/lock timeouts. That initial attempt is retained separately and is not counted as application acceptance.

Logs and SHA256SUMS: `/var/tmp/cordis-root-postgres-pc5yofd7`.
