# Final removal of Agent business DI facades

A final comparison with stage 4 of the approved plan found three remaining
`DIContainer` business facades: conversation persistence, execution-event
persistence and AgentService construction. The Provider and recovery adapters still
used the two repository facades; the AgentService callers were behind unconditional
legacy-runtime retirement exceptions. No V1 registry had resumed execution.

## Runtime change

The application shell no longer constructs AgentContainer or exports those three
facades. Shared infrastructure reuse and scoped DB handles remain intact. Workspace
Provider and recovery persistence now resolve the existing declared conversation
and event repository factories through `lease_workspace_runtime_repositories_v2`.
No new manifest, artifact digest, catalog or static SQL fallback is introduced.

The helper holds an admitted ROOT generation and its operation until repository
use finishes, including streaming, cancellation and terminal persistence. It does
not bind generation or operation ContextVars. The Provider authorizes the request
before opening the repository lease; the separate scoped Agent reservation retains
its original authorization and execution boundary. Recovery retains its exact
conversation identity checks before reading events or writing terminal evidence.

The already-retired worker and retry launch functions retain their signatures and
original retirement errors. Their unreachable implementations and exclusively used
private helpers are removed. This does not restore a legacy workspace execution
path. Tests of removed dead implementations are replaced by retirement assertions;
tests of retained active behavior continue to run.

## Validation

- DI shell and facade retirement: 19 passed; the new assertions first failed against
  the previous business assembly.
- Repository lease: nine passed with the real Loader, including HMR retirement,
  cancellation, exceptional exit, ContextVar isolation, invalid identity and missing
  Providers. Ruff and Pyright passed.
- Provider and recovery: 45 passed, including existing authorization, deduplication,
  replay and terminal evidence checks, plus explicit stream/persistence lease tests.
  Ruff and Pyright passed.
- Generation output and contract completeness checks passed without regeneration.

The obsolete launch cleanup passed 76 focused tests covering retained worker/goal
behavior, draining, Redis authority and retirement. Its 37 removed tests exercised
only deleted unreachable helpers. Ruff passed; Pyright reported zero errors and
174 pre-existing warnings (the prior files reported 191 warnings). GitNexus reported
MEDIUM for the application container and Provider class, LOW for the affected
facades and launch paths. New helper symbols are absent from the existing index;
manual call-site inspection and real lifecycle tests supplement the graph evidence.

The deployment reuses the already-admitted generation-2 bundle because this change
modifies the transport boundary and removes dead code, without modifying a
manifest-bound module. A final real startup/shutdown check and exact persisted
publication preservation check are required after the source commit.
