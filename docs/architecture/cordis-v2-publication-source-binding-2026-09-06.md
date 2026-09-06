# Cordis V2 durable publication source binding

New scoped publications retain the canonical DesiredBundleSet used to compose their verified snapshot in a separate immutable `platform_plugin_v2_publication_sources` table. Its publication ID primary key and composite scope/publication foreign key bind one source to one publication. The source includes exact Bundle references and the immutable ProfileSource reference. These are provenance records, not replacements for current signature, installation, permission and revocation checks at recovery time.

The scoped coordinator verifies archive identities against the fenced desired Bundle references, then writes requested publication and source binding in one database transaction before Loader apply. A binding failure rolls back the requested publication and cannot run candidate effects. Same-publication replay accepts only identical source payloads. Reads reject another scope and validate the canonical desired revision against the publication generation.

Explicit republish of the last globally ready publication copies its proven source binding in the same transaction. It does not bind current desired configuration. A publication without a binding remains unbound; this batch does not guess or backfill historical lineage. Public distribution JSON retains the existing descriptor/snapshot/envelope fields.

Migration `d72e6b8f0a41`, parent `c69d15e50ba3`, was generated with Alembic produce_migrations/render_python_code against isolated PostgreSQL, reviewed as a single-table addition, and verified for upgrade/downgrade/re-upgrade, cross-scope FK rejection and parent deletion RESTRICT. This is the existing ledger migration subset plus the new migration; it is not proof of the entire historical migration chain. The owned test container was removed.

Recovery state reading, exact last-good restaging, current archive revalidation and application restart admission remain to implement. ROOT publication lineage, historical backfill, final V1 retirement, full migration-chain validation and native acceptance remain open.

## Validation

- Existing coordinator/repository/publication service regression: 23 passed, 21 warnings, 82.48 seconds.
- New source-binding tests: 5 passed, including source immutability, transaction failure with zero apply, scope rejection and republish lineage.
- Pyright: 0 errors, 0 warnings. Ruff, generated protocol and completeness checks passed.
- PostgreSQL migration evidence and reproducible autogeneration script, test logs and SHA256SUMS: `/var/tmp/cordis-publication-source-8fccvhy7`.
