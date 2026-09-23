# Cordis V2 retirement recovery scope — 2026-09-07

The V1 retirement preflight now exports only a ROOT globally-ready V2 publication. Publication versions are allocated independently by scope, so ordering all ready rows by version could previously select a tenant publication as the platform disaster-recovery baseline. Both automatic selection and an explicit foreign nonce now respect the ROOT scope boundary; the existing export schema and `migration_globally_ready_missing` error remain unchanged.

The regression was reproduced before the query change: four failing scope cases and two existing passing cases. After the change, the complete repository test file passed all six cases in 48.55 seconds. Tests cover a lower-version ROOT publication with a higher-version tenant publication, an explicit tenant nonce, and a database containing only the tenant publication. Ruff and focused Pyright passed with zero errors/warnings. Direct source review also verified the preflight and persisted verification callers.

Logs: `/tmp/cordis-retirement-root-scope-red.log`, `/tmp/cordis-retirement-root-scope-final.log`, `/tmp/cordis-retirement-root-scope-pyright.log`.

Operational preflight has not run against the configured development database. Its loopback connection was refused, so V1 desired rows, conversion records and ROOT ready state are unknown rather than empty. The existing `memstack-postgres` container and its persistent volume were found stopped. The shared database was not started during the ongoing broad test run, and isolated test databases were not substituted for it. Host PostgreSQL backup tools were also unavailable in the inspected paths.

Database recovery, a private backup and actual isolated restore, reviewed offline conversion materials, full composition/readiness, parity and real native acceptance remain release gates. No destructive retirement or business-data conversion was performed in this batch.
