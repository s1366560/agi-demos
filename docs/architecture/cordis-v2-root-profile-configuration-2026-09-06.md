# Cordis V2 explicit ROOT profile configuration

Marketplace republication now reads the exact ProfileSource referenced by the current ROOT DesiredBundleSet from ROOT storage before fetching Bundle artifacts. Missing, wrong-revision, wrong-digest and foreign-scope sources do not trigger artifact loading or publication. An absent source row is compatible only with the exact immutable builtin source ID, revision and digest; stored ROOT source content takes precedence.

A new RootProfileInitializationServiceV2 prepares first-use configuration under the ROOT ScopeHead lock. The caller must supply a boolean Workspace Core choice. The service declares replacements for the three actual builtin Workspace Core entries, computes source and desired digests, validates composition and saves both records in one transaction. Both enabled and disabled choices are explicit. Existing ROOT desired configuration is returned unchanged, and source CAS conflict or transaction failure leaves no partial desired state.

The initializer is not yet connected to application startup. Startup recovery still contains the earlier Workspace Core activation overlay; removing that override and publishing from the exact stored configuration is the next required integration batch. Existing ROOT configurations require explicit revision-bound migration rather than guessing intent from disabled entries. Initialized child scopes retain their own snapshots.

## Validation

- Combined initialization, source rejection, marketplace install/republication and marketplace router tests: 26 passed, 21 warnings, 53.39 seconds.
- Actual ROOT generation republication proves an explicitly disabled canvas contribution stays disabled; the old builtin-reference case still passes.
- Pyright: zero errors and warnings. Ruff passes.
- Dedicated PostgreSQL concurrency coverage uses two independent services/sessions in a fresh migrated database, requiring empty ROOT state without deleting existing data.

The publisher and route entry impact analysis reported LOW with four and three upstream relationships respectively. The new initializer is not indexed, so UNKNOWN is not treated as low-risk proof.

Provider user/Workspace authorization, Provider scoped stream wiring, startup source convergence, historical migration recovery, V1 retirement and final native acceptance remain incomplete. This batch did not run a model or native Electron flow.

PostgreSQL final result: 15 passed, 21 warnings, 13.49 seconds; isolated container cleanup succeeded. Generator and contract completeness passed. Evidence/checksums: `/var/tmp/cordis-root-config-n2f17xgc`. This migration slice does not prove the full historical migration chain.
