# Cordis V2 scoped Workspace Core ownership

Scoped builtin definitions now borrow the supplying ROOT generation's typed Workspace Core runtime. Each applied scoped module retains an owner generation lease and releases only that lease at disposal. It does not construct another client, Provider adapter or event sink, and does not call the shared runtime's disposer independently.

This makes explicitly enabled workspace prompt-context profiles loadable with the application-owned Workspace Core resources. It does not enable disabled Profile entries or change stored source content.

The new definition checks the declared strategy, resolves the exact Workspace Core service from its leased owner, checks the service type, and releases the lease on failure. Existing scope validation and the Loader's dependency ordering still apply. Scoped factory impact is UNKNOWN because GitNexus has not indexed it; focused runtime tests provide the ownership evidence.

## Validation scope

The new tests use actual builtin profiles and the existing explicit Workspace Core activation overlay, then the real service-closure projector, Loader and scoped registry. They prove prompt-context resolution, shared runtime identity, two independent scopes, retained resources after ROOT retirement, exactly one final Provider drain, and rejection/lease cleanup for invalid or missing owner services. External client and Provider bodies are test doubles; no network or model acceptance is claimed.

## Provider authorization and configuration work still required

The internal Provider endpoint currently authenticates a Bearer service token using constant-time comparison. ProviderWorkspaceScope validates frame shape. Existing conversation checks compare tenant/project/user/workspace and task correlation; new conversation IDs are deterministic. None of those checks proves current SQL project/tenant membership or authoritative Workspace membership.

Before scoped initialization, the Provider path must validate Project ancestry, UserTenant and UserProject membership and use the selected Core access verifier. Preserve correlation duplicate/terminal replay behavior. Both chat webhook and plan-dispatch paths require this boundary. Bind scoped admission around the full stream, independently of the outer ROOT reservation.

A separate mismatch remains: ROOT startup explicitly activates Workspace Core services while the builtin Bundle base layer retains disabled entries and the default ProfileSource has no enabling replacements. Fix the authoritative source/desired initialization or migration, preserving explicit user disable choices; do not hide this mismatch with a projection-time override. WorkspaceCore source activation, provider admission, historical recovery, V1 retirement and final native acceptance remain uncompleted.

The ROOT source audit also found that marketplace republication currently composes the fixed production source rather than the exact stored ROOT source. Next work must make ROOT initialization, startup recovery and republication consume the same explicit configuration. For a new ROOT desired set, create source/desired together under the ROOT head lock with declared replacements. Existing records require an explicit revision-bound migration; never infer user intent from disabled values. Initialized child scopes retain their private snapshots. The production base Bundle should not be rewritten to change the meaning of old references.

Final regression: 47 passed, 21 warnings, 104.83 seconds. Pyright: zero errors/warnings. Ruff, generator and contract completeness passed. Evidence and checksums: `/var/tmp/cordis-scoped-workspace-42vc2c53`.
