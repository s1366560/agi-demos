# Cordis V2 live recovery PostgreSQL verification — 2026-09-06

The isolated PostgreSQL runner now includes two live recovery cases. Both use real startup, marketplace publication, verified archive loading and the same running Host. A mutation session commits the request then raises; recovery preserves the original nonce, version and generation and applies only once. The second case also commits the actual recovery receipt then raises; a normal recovery attempt resumes admission without another apply or receipt event.

The tests retain a separate PostgreSQL connection and assert that the actual receipt transaction has a different backend PID. Both end with exactly two requested publications and two real receipt events; another run is a no-op.

Validation: the expanded seven-file runner passed all 22 tests in 136.29 seconds, with no skips. Owned container cleanup exited 0. Ruff and runner Pyright pass; Pyright reports zero errors and warnings. Evidence logs and SHA256 manifest: /var/tmp/cordis-live-postgres-ic42p86y.

This verifies the seven-migration ledger slice through d72e6b8f0a41. It does not prove the historical Alembic chain, atomic source fencing inside receipt persistence, stale pending receipt supersession, final V1 retirement or final native acceptance.
