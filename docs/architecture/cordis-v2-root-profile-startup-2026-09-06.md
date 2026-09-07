# Cordis V2 startup from stored ROOT configuration

Production startup with a session factory now initializes missing ROOT configuration and composes the exact stored source and desired Bundle references. Bundle loading uses the installed archive verifier and deployment trust/registry settings. Existing ROOT source choices take precedence over process factory availability and current startup options.

First initialization records explicit Workspace Core and Agent Pool choices, including pool configuration, as source replacements. Subsequent startup does not rewrite those choices. A candidate identical to the durable snapshot replays its generation; changed configuration publishes above both durable and latest-requested counters. A new candidate NACK retains the actual prior durable ACK version/digest rather than incorrectly labeling the failed candidate as last-good.

The no-session-factory isolated startup path retains the earlier bootstrap behavior. The production main passes a session factory and uses the stored-configuration path. Startup cancellation closes the uninstalled runtime host.

## Legacy migration boundary

A durable ROOT distribution without a DesiredBundleSet is not safely equivalent to a fresh database. Startup rejects that case with root_profile_migration_required before default initialization, leaving old configuration intact. An explicit migration must bind installed Bundles and the intended ProfileSource; no decision is inferred from disabled entries. This migration remains required work, not completed acceptance.

## Evidence and limits

Real SQL/Loader tests cover saved disabled Workspace Core with an available factory (factory not invoked), first source/snapshot equality, unchanged restart generation/digest, changed source revision, explicit Workspace Core activation, and rejection of legacy durable state without desired. Agent Pool source tests verify explicit switch/config and unchanged existing ROOT records. Cancellation and failed-candidate receipt paths are tested separately.

Initial regression caught an obsolete expectation that supplying a Workspace Core factory should override saved disabled configuration. That fixture now explicitly saves an activation source revision before expecting a new enabled generation; independent tests retain the disabled-choice guarantee.

This batch does not prove continuous fencing against concurrent administrative mutations during startup, the full historical migration chain, actual Provider/LLM calls or native Electron acceptance. Provider membership/scoped stream wiring, legacy conversion and final V1 retirement remain incomplete.

Validation: new configuration/lifecycle suite 17 passed; existing startup suite 8 passed; Workspace Core suite 13 passed; updated/NACK targeted rerun 3 passed (overlaps earlier suites). PostgreSQL slice 15 passed with successful temporary-container cleanup. Pyright zero errors/warnings; Ruff, generator and completeness checks passed. Evidence/checksums: `/var/tmp/cordis-root-startup-1_e258k2`.
