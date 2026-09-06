# Scoped ProfileSource consumption and borrowed infrastructure

`ScopedProfilePublicationServiceV2` now loads the exact stored scope desired/source,
checks verified Bundle identities, composes layers and projects explicit required
services before calling the scoped publication coordinator. The caller supplies
the trusted archive loader and service requirements. Stored provenance never grants
artifact trust, and this service performs no arbitrary URL fetch.

The snapshot generation follows the desired revision. The coordinator checks the
expected desired value again inside the request transaction while holding ScopeHead.
An intervening desired update rejects the candidate before requested persistence or
local apply, and rolls back the allocated version. Merely checking before acquiring
the database lock would leave a race.

The signed-Bundle end-to-end test uses real user authentication to POST the source
and PUT desired, then runs this service through the real composer, service projector,
Loader, receipt persistence and lease admission. The actual provider executes the
configuration from the stored source. This is a conformance provider test, not a
production Agent turn or native application acceptance.

The Sandbox provider has an explicit `projected_runtime` mode. It borrows an existing
typed service, rejects mixed factory/projected sources, retains required/configuration
checks and does not synchronize Docker, start another global reaper or close borrowed
resources. The upper owner must retain the supplying generation lease. Tests prove
that borrowed disposal does not close the resource and that releasing the last owner
lease closes it once. Only the two Sandbox module artifact digests changed in the
generated catalog; their contracts remain unchanged.

Production startup and Agent boundary ownership are still to be connected. Graph
factories need tenant binding, shared infrastructure must outlive scoped leases, and
process-shared SubAgent state must not be presented as scope-private. This batch does
not complete Stage 6, V1 retirement or final native acceptance.

Validation: the combined unit/router regression passed 40 tests; isolated real
PostgreSQL regression passed 13 tests. Protocol generation and contract completeness
checks passed. PostgreSQL coverage uses the documented migration slice, not the full
historical migration chain. Evidence and SHA-256 inventory: `/var/tmp/cordis-scoped-consumption-y50scnxc`.

Post-commit regression at `03d260ab8`: full Desktop suite passed 4,131 tests,
with 2 skipped and 0 failures (94.82 seconds). Four focused Web suites passed all
26 tests. These are automated regressions, not a new native UI acceptance run.
