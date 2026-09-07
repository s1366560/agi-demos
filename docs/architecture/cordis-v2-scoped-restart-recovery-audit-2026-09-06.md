# Scoped runtime restart recovery: bounded audit

Current source audit at `610c7a373`. No runtime recovery implementation is claimed by this document. The existing publish_current path composes current desired and allocates a new version; it is NOT a restart restore operation.

## Minimal API

- Repository `read_recovery_state(data_plane_id)` returns one immutable scope-bound DTO read under ScopeHead lock: latest requested distribution, retained applied/last-good distribution, and that plane's actual latest receipt identity/status (nonce, requested/applied version+digest, receipt generation). Current public repository only exposes last_good_distribution and latest_requested_distribution; neither alone proves latest was receipted.
- Coordinator `restore_last_good(scope, *, verified_archives, expected_recovery_state)`: serialized under coordinator slot lock, no version allocation, no record_requested_distribution, no desired composition. Read/fence durable state, canonical-parse retained snapshot/envelope, stage it via registry.publish using EXACT saved envelope and verified artifacts, require real local ACK, then re-read/fence same durable state before opening admission. An unreceipted latest request keeps admission blocked. Do not POST/re-record an old receipt against a superseded nonce.
- App runtime `restore_existing(scope)` resolves archived bytes corresponding to the saved publication, invokes restore, then acquire returns the normal durably guarded reservation. This operation cannot implicitly call publish_current. Existing acquire checks must continue to compare DB identities on every new admission.

## State handling

1. No retained last-good: fail unavailable. Do not interpret current desired as proof of previously accepted runtime.
2. Latest requested == retained ACK: exact snapshot/envelope restage, local ACK, fence DB state unchanged, then admit.
3. Latest has recorded NACK and retained prior ACK: restore retained ACK resources only; preserve the actual latest-NACK observation identity so normal coordinator acquire can compare latest/observed and last-good/admitted. No attempt to stage latest NACK candidate merely to synthesize an observation.
4. Latest requested has no corresponding persisted receipt: remain blocked. Old last-good may be reconstructed as a dormant retained candidate, but do not admit or invent a NACK. Explicit reconciliation of latest is a separate operation.
5. Desired changes independently: restore must not publish it. Existing coordinator admission gates compare latest requested + last-good, not current desired; keep this behavior until an explicit new publication applies desired. New desired is not automatically execution authority and also not automatically a revocation.
6. State changes while bytes load/stage: fence exact latest + receipt + retained identities again. Do not open admission for stale recovery. Release rejected local candidate/resources according to existing registry lifecycle; retain pinned older operations.
7. Local restage NACK: keep admission blocked; original durable ACK is historical evidence, not proof this process can instantiate its resources. No root fallback.
8. Revoked/uninstalled archive or revoked permission/trust: loader must reject even when historical ACK exists. Do not use cached VerifiedBundleArchive as indefinite trust. Current ScopedInstalledBundleLoaderV2 creates a fresh governance session/client each load; InstalledVerifiedBundleLoaderV2 checks installed + not revoked, registry allowlist, exact artifact digest/signature/provenance and current permission grants.

## Critical archive binding gap

record_requested_distribution persists PlatformPluginDistributionV2(snapshot,envelope,descriptor). It does not persist the DesiredBundleSet/ProfileSource/BundleReference list used to create this snapshot. Projection removes unused modules but retains original module artifact reference, which is not itself a complete marketplace BundleReference. Bundle ID must not be guessed from plugin_id.

Current desired can differ from the publication being restored, so loading current desired bundles is not a valid historical-artifact recovery method. Correct minimal options:
- Persist immutable publication -> exact verified bundle references at requested-publication commit, scope-bound and transactionally linked, then reverify these references at restore.
- For an initial bounded builtin-only restore, use current production baseline archive only when its exact verified module artifacts/contracts cover every enabled restored Python module; mismatches fail closed. Do not claim marketplace historical restoration in this mode.
- A historical desired-set search requires an explicit proven binding to the publication (or exact deterministic reproduction of snapshot including projection roots); merely selecting the closest revision is not proof. Current desired history alone does not contain the requested publication's selected service-root closure provenance.

Current registry supports candidate bound verified archives and verifies same-digest publications' bytes even when reconciler skips Loader staging. Keep that trust path during restore; do not fall back to raw repository resolver for marketplace modules. Existing slot artifact-mode mismatch is intentional.

## Existing implementation reuse

- ScopedPublicationCoordinatorV2 slot lock, blocked/pending/admitted/observed state and cancellation-owned lifecycle tasks.
- PlatformPluginRuntimeHostV2 exact distribution map and real Loader receipt, ScopedRuntimeRegistryV2 host-incarnation reservations.
- Repository ScopeLedgerBindingV2 lock plus existing last-good/apply-state rows; add a DTO reader instead of leaking ORM state to app runtime.
- ScopedInstalledBundleLoaderV2 / InstalledVerifiedBundleLoaderV2 current governance and transport validation.

## Test gates

Extend test_scoped_publication_coordinator.py and scoped startup tests with two separate coordinator/registry instances on the same real SQL fixture: ACK restore preserves nonce/version and does not append requested rows; NACK latest restores old services while maintaining latest observation; unreceipted latest cannot acquire; desired changed is not published; stale restore DB fence fails; revoked archive stops restore; local candidate failure cleans resources; cancellation leaves no unowned restore task/lease; cross-scope identical digest cannot restore another authority.

Reuse real PostgreSQL scoped ledger concurrency tests for restore vs new publish receipt races, and installed verified bundle loader trust/revocation fixtures for archive recovery. A restarted in-memory registry seeded from current desired is not a restore test.

## Persistence decision

Add an independent immutable publication-source binding table via an autogenerated, reviewed Alembic migration. Its identity must include scope_key plus publication_id with a composite FK to the existing publication table. Persist the canonical exact desired/source and verified Bundle references in the same requested-publication transaction, before candidate apply. Do not rewrite old rows to guess missing lineage. Missing historical bindings require an explicit validated migration or must fail unavailable.

Keep binding metadata outside distribution JSON. Python `runtime_host.py:163` requires exactly descriptor/snapshot/envelope; TypeScript `agi-stack/packages/plugin-runtime/src/distribution.ts:33` permits exactly schema_version/descriptor/snapshot/envelope; Rust `agi-stack/crates/plugin-host/src/protocol_v2/distribution.rs:47` rejects unknown fields. Python direct probe confirmed an extra source_binding is rejected before staging, with no generation created. TypeScript/Rust conclusions are source inspection, not new executed tests.

## Implementation order

1. Add and migrate the scope/publication source-binding model and repository; transaction, nonce replay, cross-scope and rollback tests, then isolated PostgreSQL verification.
2. Write the binding from scoped publication only after verified archives and exact desired/source validation; keep publication+binding atomic. Explicit rollback/republication copies the proven binding rather than current desired.
3. Add a locked immutable recovery-state reader containing actual receipt status and latest/retained identities.
4. Implement exact last-good restaging and final durable fence with freshly reverified archives, including latest-NACK and unreceipted-latest behavior described above.
5. Connect authorized application recovery consumers and test two independent runtime instances sharing the persisted ledger.

This audit changes the next implementation step from attempting in-memory replay to establishing trustworthy persisted artifact lineage. Final V1 retirement, full historical migration-chain validation and native acceptance remain outstanding.
