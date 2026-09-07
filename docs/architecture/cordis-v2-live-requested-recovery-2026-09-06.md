# Cordis V2 live requested recovery — 2026-09-06

## Delivered behavior

The running marketplace recovery loop now resumes a committed ROOT request that has no Python receipt, as well as retrying a retained actual receipt. It loads the exact requested nonce, version and generation, validates its immutable source binding against current desired state and policy, re-verifies archives and recomposes the complete requested snapshot. Startup and live recovery share this preparation logic.

The live path performs its final pre-apply check under the route coordinator lock. If foreground publication completed while the candidate was being prepared, recovery does not call Host.apply again. Actual staging uses the existing Host and route coordinator, and its real receipt must commit before new admission resumes.

The coordinator retains the receipt authority callback with the actual pending outcome and invokes it on every persistence retry. A desired-state change during staging therefore remains rejected on subsequent retries. The callback accepts either the original unreceipted state or the exact matching durable actual ACK/NACK for the same request, while still validating desired state and source. This allows retry after a successful receipt commit whose response was lost, without another apply or duplicate receipt event.

## Validation

- Five live SQL/Loader cases passed in 91.60 seconds: same-Host recovery after requested commit followed by error; foreground completion before background apply; incompatible bound source; desired CAS during staging remains rejected on retry; actual receipt commit followed by error recovers idempotently.
- Before the retained callback extension, original live and background receipt tests passed together: 9 passed in 141.17 seconds. Startup, route receipt and scoped lifespan regression: 17 passed in 146.47 seconds. These runs overlap the final focused suites.
- Final route receipt/startup regression: 12 passed in 147.31 seconds. Existing PostgreSQL gate: 20 passed in 96.46 seconds, no skips, owned container cleanup exit 0.
- Evidence logs and SHA256 manifest: /var/tmp/cordis-live-requested-nq2rr0zt.
- Ruff, generated protocol and contract completeness checks pass. Focused production Pyright reports zero errors and warnings.
- GitNexus coordinator analysis reported LOW risk, 3 direct callers and 13 upstream impacts. Recent recovery symbols were unindexed; direct review covered startup, background recovery, route publication and retries.

## Boundaries

This batch covers exact unapplied-request recovery on a live Host. Replacing a Host with an actual stale pending receipt after supersession remains separate work. Source checks occur at recovery boundaries; they do not implement continuous governance admission or an atomic desired-source check inside receipt persistence. Historical lineage migration, V1 retirement, final fixed-revision full suites, parity rebinding and native acceptance remain outstanding. The PostgreSQL runner verifies a seven-migration slice, not the complete historical Alembic chain.
