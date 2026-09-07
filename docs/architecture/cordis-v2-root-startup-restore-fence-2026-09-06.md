# Cordis V2 bound ROOT startup restore fences

The unchanged-runtime startup branch now reads the locked ROOT recovery state before restoring. It requires the exact retained distribution, a real receipt for the latest request and an immutable retained source binding. A newer unreceipted request blocks this restore; missing historical lineage requires explicit migration. Current desired must still match the configuration used to load the candidate.

Equal runtime content does not make different desired revisions interchangeable. If retained lineage differs from current desired, startup takes the normal new-publication path, allocating a new generation/nonce and storing its own source binding. It does not attach current desired to an old publication.

An exact restore supplies the verified historical Bundle references to Host.apply_distribution. After real staging, startup rereads both recovery state and desired under the ROOT lock and rejects any change before installing the host. A local NACK raises and closes the uninstalled host without writing a new publication or receipt. A persisted latest NACK can continue to describe the earlier ACK; successful local restore does not rewrite that NACK as an ACK.

## Evidence boundary and remaining work

These are startup point-in-time fences. They do not provide continuous ROOT admission checks after installation, resolve an unreceipted request, or backfill legacy unbound history. Different-content startup remains an explicit new configured publication via the requested-before-apply path. Marketplace durability/pending-receipt admission, PostgreSQL ROOT race acceptance, complete historical migrations, final V1 retirement, parity rebinding and native acceptance remain open.

Tests use real SQL persistence, actual startup/route staging and verified-byte fault injection. Separate SQLite sessions are not PostgreSQL multi-connection isolation evidence.

## Validation

- Existing ROOT configuration/restart and verified-byte fault tests: 7 passed, 93.50 seconds.
- New restore fences: 6 passed, 108.48 seconds; additional real latest-NACK case: 1 passed, 23.09 seconds. The unreceipted-request case was rerun after strengthening its exact error-code assertion: 1 passed, 17.42 seconds (overlaps the six).
- Ruff, protocol generation/completeness and Pyright passed; Pyright 0 errors/0 warnings.
- Logs and SHA256SUMS: `/var/tmp/cordis-root-restore-397iwkfe`.
- The separately running cross-batch v2 unit baseline is not counted as a final-revision gate.
