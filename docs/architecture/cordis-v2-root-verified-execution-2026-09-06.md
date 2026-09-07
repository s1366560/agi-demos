# Cordis V2 ROOT startup verified execution

Persistent ROOT startup now supplies its freshly verified archives to the actual Host apply path for both a new candidate and an unchanged durable distribution. Previously it used archive manifests for composition while the Loader independently resolved execution artifacts without comparing those bytes with the archive.

Host freezes the archive sequence before waiting for its publication lock. Reconciler and Loader receive the candidate explicitly; no ContextVar, shared mutable resolver or persistent archive cache is introduced. Loader checks target contracts, artifact metadata and digests as before, additionally requiring the resolved canonical bytes to equal the corresponding verified archive bytes. The same resolved artifact objects are passed to dynamic loading. Empty archives are a strict candidate and cannot silently select the ordinary path.

Same-digest fast ACK rechecks execution bytes before advancing the applied version. Failed verification retains the old generation and its leases. Existing calls without archives retain their prior behavior, including ordinary hot updates; that compatibility is not proof those callers have archive-bound governance.

## Evidence boundary

The injected builtin definition factory branch remains trusted host code; byte comparison does not convert those factories into dynamically loaded archive modules. Separate tests cover a Loader with no injected definitions and prove the compared resolved object is the one loaded, with zero load/apply on mismatch.

Real persistent ROOT startup tests inject corruption after archive verification and require rejection before route staging for both fresh startup and durable restore. This is fault injection at the trust-result boundary, not a successful malicious archive signature verification.

## Remaining ROOT work

ROOT publication-source binding and transaction ordering are still incomplete. Startup and marketplace publication currently apply before recording the publication ledger. The source repository assumes runtime generation equals desired revision, whereas ROOT independently advances runtime generation. A correct lineage change must address those counters and capture the exact candidate in the publication transaction; it cannot reread current desired after staging. Marketplace route publication must also carry its verified archives through to execution. Historical unbound recovery, continuous governance fencing, complete migration-chain acceptance, V1 retirement and final native/parity acceptance remain open.

## Validation

- Runtime/Host/Reconciler/cancellation/scoped/watcher and actual ROOT fault injection: 85 passed, 21 warnings, 96.60 seconds.
- Candidate archive and dynamic load identity: 11 passed.
- Existing persistent ROOT startup: 5 passed (within the earlier 14-case focused run, whose 9 archive cases overlap the 11-case run).
- Ruff and protocol generation/completeness checks passed. New attestation helper and ROOT startup Pyright: 0 errors/0 warnings. The five production modules together report 0 errors/34 warnings in legacy runtime/host/reconciler code; this is not a warning-free broad type check.
- Logs and SHA256SUMS: `/var/tmp/cordis-root-verified-gi545iu4`.
- An earlier whole v2 unit baseline remains separate; it is not counted as a completed gate in this report.
