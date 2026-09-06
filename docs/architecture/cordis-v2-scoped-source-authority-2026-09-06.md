# Scoped source persistence and publication authorization

The new publication-scope resolver validates resource ancestry from stored Tenant,
Project and Conversation rows before granting writes. ROOT requires platform
administrator authority. TENANT requires its owner/admin or a platform administrator.
PROJECT requires current tenant membership and project owner/admin. SESSION additionally
requires conversation ownership; session identity is the actual Conversation ID.
Project/session checks have no platform-administrator bypass. This is a new publication
write contract, not permission for ordinary conversation reading or execution.

ProfileSource storage is immutable and private to full scope/source/revision identity.
Writes use the scope-head transaction lock and compare-and-swap; first revision is one
with expected revision absent. Exact duplicate writes are idempotent. Reads require the
exact digest and revalidate stored identity and payload. Layers may belong to the owner
or its ancestors, never siblings. Stored provenance is data, not signature verification
or authorization, and the repository performs no external fetch.

Migration `c69d15e50ba3` follows `b58c04d49a92`. It was generated against isolated
PostgreSQL and reviewed, including the protocol's 71-character prefixed digest.
Alembic and the existing schema initializer explicitly register the separate model.
The isolated migration slice passed upgrade, downgrade and re-upgrade. This does not
repair or validate the full historical migration chain.

Validation: 23 authorization/source unit tests passed, including revoked membership,
forged ancestry, unauthorized owners, exact reads and source integrity. Five real
PostgreSQL tests passed: four ledger regressions and a source test with six concurrent
identical first writes, competing revision CAS, retained immutable history and ROOT
read isolation. Seven authenticated ROOT HTTP regressions passed separately.

These components are not yet connected to a scoped publication endpoint or Agent turn.
Production wiring must coordinate candidate preparation, durable requested publication,
activation and real receipt persistence before business admission. It also needs an
explicit dependency closure for each Agent consumer and exact host leases/distribution
for child operations. Reusing the ROOT host or merely labeling its operation SESSION
does not provide scoped runtime isolation. Final V1 retirement and native acceptance
remain outstanding.

Reproduction scripts, logs, autogenerate output and the detailed pending wiring design
are retained with hashes in `/var/tmp/cordis-scope-source-z44d1qgc`.
