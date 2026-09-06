# Cordis V2 scoped publication ledger

The publication repository binds to one validated scope, defaulting to ROOT.
Publications, current data-plane state, receipt events, readiness and republish
queries share that identity. A scope identity is not an authorization grant.
Production scoped authentication and runtime-registry wiring remain separate work.

Each scope has a transaction-locked version high-water mark. Concurrent first
allocations serialize; rollback releases a reservation. Incoming publications
retain their supplied versions, including distinct nonces at the same version.
Republishing allocates above the high-water mark and may leave reserved-version
gaps. Nonces remain globally unique. A competing cross-scope insert rolls back a
savepoint and returns a domain conflict without aborting the caller's transaction
or degrading an existing publication.

Migration `b58c04d49a92`, following `a47a93b38981`, was reviewed from an actual
isolated PostgreSQL Alembic autogenerate diff. It backfills existing rows as ROOT,
initializes the head from the maximum requested version, and replaces publication
references with composite scope foreign keys. Downgrade locks the four tables and
refuses any non-ROOT data, including a scoped allocation head.

Validation used a disposable PostgreSQL 16 container and actual prior ledger
migrations `dc206dd13ac3`, `e91f4c7b2d60` and credential migration `f43f5cd2fb21`.
Legacy publication/state/event values survived upgrade, downgrade and re-upgrade;
the seeded version 41 became the ROOT high-water mark. This is a migration slice,
not proof of the full historical migration chain.

The final compatibility and scope unit suite passed 19 tests (90.31 seconds).
Four real PostgreSQL tests passed: scoped downgrade refusal, eight concurrent
first allocations with rollback, a forced cross-scope nonce race with transaction
recovery, and six concurrent identical first receipts with one event, independent
same-plane state and database rejection of a foreign-scope reference.

Autogenerate input/output, the isolated database runner and PostgreSQL test log
are retained with hashes in `/var/tmp/cordis-scoped-ledger-ku4urjz_`.
Final V1 retirement, full historical migration recovery and final native acceptance
are not completed by this batch.

The real-authentication HTTP suite additionally passed seven tests. It verifies
that both ROOT distribution and public Web-view endpoints remain unchanged when
a tenant publication has a higher version, and return 404 when only scoped data
exists. Only the database dependency is overridden; real user and workload
credentials exercise the production router. Log: `/tmp/cordis-root-http-scope-isolation.log`.
