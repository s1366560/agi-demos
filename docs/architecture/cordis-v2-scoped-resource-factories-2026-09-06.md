# Scoped runtime resource factories

`ScopedRuntimeRegistryV2` accepts an explicit synchronous scope-to-definitions factory.
It is called for a new host incarnation with the canonical full scope; fixed definitions
and a factory are mutually exclusive. Existing hosts retain their original definitions.

`scoped_builtin_runtime_definitions_v2` binds the graph factory to the explicit tenant,
borrows process Redis and replaces the declared Sandbox module with a leased projection.
Profile service-closure projection still determines which definitions actually apply.
The factory rejects ROOT; it is not a substitute for publication authorization.

Each Sandbox apply acquires the supplied owner host's generation, resolves its typed
Sandbox runtime and holds that lease until the scoped candidate/generation disposes.
It starts no maintenance loop and performs no direct borrowed-resource cleanup. Closing
the owner host does not close the Sandbox while a scoped generation still has an active
operation lease. Candidate projection failure releases the owner lease.

`create_native_graph_adapter` now closes an internally allocated Neo4j client if any
subsequent construction stage fails, including cancellation. Externally supplied clients
remain caller-owned on failure. A cleanup failure preserves both original exceptions.
Successful adapter ownership is unchanged.

Production startup and Agent admission are not wired by this batch. Bundle-loader review
also identified a necessary trust gap: stored marketplace metadata does not retain archive
bytes, production signer configuration is not connected, and verified archive bytes must
be bound to the exact resolver used by scoped execution. Passing verified manifests alone
does not prove that binding. This must be fixed before claiming trusted production scoped
execution. Stage 6, V1 retirement and final native acceptance remain incomplete.

Validation: combined ownership/registry/boundary/coordinator regression passed 56 tests.
The final scoped factory suite passed 5 tests, including the subsequently added real
Loader tenant graph isolation test. These counts overlap. Protocol generation/check,
contract completeness, Ruff and whitespace checks passed. Evidence and hashes: `/var/tmp/cordis-scoped-resource-factories-zaqbvlhf`.
