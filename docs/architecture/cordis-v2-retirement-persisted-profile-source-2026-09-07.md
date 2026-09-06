# Retirement preserves initialized ProfileSource references

The real offline retirement plan rejected the existing ROOT head with
`migration_target_profile_source_conflict`. Production startup had correctly
persisted `memstack-root-initialized-profile-source-v2`, including three enabled
Workspace Core replacements and the explicitly disabled agent pool. Its original
layers and first base Bundle matched the production baseline. The migration
service incorrectly required the unmodified static source reference.

The CLI now supplies the immutable ProfileSource repository from the same database
session as its other repositories. Migration resolves the exact scope, source ID,
revision and digest. Only the complete built-in reference can use the built-in
source fallback. Missing or invalid persisted sources remain errors. The exact
first production Bundle remains protected, and both the initial and resulting
Bundle sets undergo structural profile composition. This does not execute plugins,
fetch remote sources, reinterpret provenance as trust, or rewrite the ROOT source.

Eight isolated tests cover the initialized four-replacement layer, unchanged
desired-state preservation, missing/tampered sources, foreign-scope layers and
the protected base Bundle. They passed in 1.47 seconds. Ruff passed; Pyright
reported zero errors and zero warnings. GitNexus CLI impact classified the changed
methods and CLI factory LOW; the migration plan method has one direct caller and
four impacted symbols across the service and scripts. The index is supplemented
by direct inspection of initialization, repository validation and CLI construction.

The existing migration service, CLI and preflight regressions also passed:
15 passed, seven warnings, 4.47 seconds. These use in-memory SQLite, mocked archive
operations and temporary files; they do not modify the original database. Their
log is `/tmp/cordis-migration-existing-regression.log`.

The actual repository CLI plan then passed against the original upgraded database,
using the saved backup/export/last-ready manifest. It found zero V1 source rows and
an unchanged ROOT head at revision 1, digest
`sha256:899f98bc93a438d44c55a1298ddd2e14a6c6f6cb00d2767dd94a0a195665e7a8`.
This plan does not write a conversion audit and is not itself the final apply.

Private operational evidence is under
`/var/tmp/cordis-final-retirement-ufhyv7hu`: `profile-source-conflict.json`,
`before-conversion-verified.json`, and `conversion-plan-exact-source.json`.
The failed original plan is retained. Test and impact logs use the
`/tmp/cordis-migration-profile-source-` and `/tmp/cordis-migration-source-` prefixes.
