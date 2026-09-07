# Application-owned scoped profile runtime

The production lifespan now installs `app.state.scoped_profile_runtime_v2` after the
ROOT runtime and deployment trust configuration exist. The component owns a private
registry, durable publication coordinator and scoped Bundle loader. Internal authorized
callers explicitly supply required services to `publish_current`; `acquire` returns the
already-admitted exact host reservation for the scoped Agent operation boundary.

The Bundle loader creates independent SQL sessions and HTTP clients for each load,
uses a required registry allowlist, and delegates real OCI and signature validation to
the shared installed loader. Its default HTTP policy is bounded, disables redirects and
ambient proxy configuration, and imposes an overall timeout. Failed/cancelled loads close
both resources. It does not cache governance records, so a subsequent load sees revocation.
This does not itself fence a governance change concurrent with an in-progress publication.

Scoped definitions bind tenant graph factories and hold Sandbox owner-generation leases.
The lifecycle closes private admission before ROOT retirement. Application body failure,
cancellation and partial startup failure also execute cleanup; ROOT shutdown is attempted
even if scoped cleanup or route disposal fails. Existing admitted leases may finish after
logical retirement, with physical resource cleanup on final lease release.

The new component test uses the actual repository Bundle, SQL source/desired records,
actual artifact resolver, service closure, Loader, receipt persistence and operation lease.
It selects the runtime boundary service and proves a separate host and generation; it is
not an LLM/Agent execution acceptance test. Separate real-lifespan tests verify shutdown
ordering while substituting external startup components.

Production Agent consumers have not yet been switched to this component. They must pass
authenticated full scope and explicit service roots, then consume its admitted reservation.
Missing desired/source must not silently select the process ROOT host. V1 retirement,
historical migration-chain recovery and final native acceptance remain incomplete.

Validation: combined loader, real component, lifespan, trust, existing V2 startup and
scoped boundary regression passed 31 tests (85.22 seconds). Protocol generation/check,
contract completeness, focused Pyright, Ruff and whitespace checks passed. Evidence
with SHA-256 inventory: `/var/tmp/cordis-scoped-application-lifecycle-5hqhhypu`.
