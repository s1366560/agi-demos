# Cordis V2 final gate progress

This records completed test runs and unresolved acceptance gates. It does not mark
the eight-stage plan complete or authorize treating V1 retirement as finished.

## Completed runtime regressions

The following runs started from clean `30cfb40d8`:

| Gate | Result | Log basename |
| --- | --- | --- |
| Python V2 unit directory | 1,637 passed, 21 warnings, 2,122.02 seconds, exit 0 | cordis-final-python-v2-30cfb40d8.log |
| Rust plugin host protocol V2 | 28 passed, exit 0 | cordis-final-rust-protocol-30cfb40d8.log |
| Rust server full suite | 607 passed, exit 0 | cordis-final-rust-server-30cfb40d8.log |
| Desktop full suite | 4,131 passed, 2 skipped, exit 0 | cordis-final-desktop-30cfb40d8.log |

The Python run remained active while later commits changed a V1 export repository,
Desktop assembly, test wiring and documentation outside that tested directory.
Its result is tied to its actual starting revision, not represented as a clean run
on every later commit. The historical database stayed offline throughout the run.

Workspace-wide Rust formatting initially found one trailing blank line in an
existing worker test. Commit `dc3640d43` removed it. The complete `cargo fmt --all
-- --check` then passed in an isolated worktree at that commit.

The V1 conversion CLI, retirement preflight contract and ROOT recovery export
repository were also run together at `4e147ee0c`: 15 passed, 21 warnings,
47.57 seconds, exit 0. Log:
`/tmp/cordis-final-retirement-gates-4e147ee0c.log`. These are regression tests, not
an operational migration of the original database.

The generated V2 protocol check and complete contract inventory check passed again
at `259dc96d2` after the native tool-contract changes.

## Full-profile renderer extraction

Commit `2f4241b4e` added the production renderer factory and full-profile three-plane
integration gate. Real HTTP/PostgreSQL integration passed, including independent
sidecar and renderer rejections preserving each plane's prior applied identity.
The final import-layout wiring run passed all 192 tests.

The post-commit Desktop full run at `2f4241b4e` ended with 4,130 passed, one failed
and two skipped. Its sole failure was
`desktop-parity-reviewed-additional-web-entries.test.mjs`: the old audited revision
`5959268ef` no longer matches the extracted production hook. The generator's source
integrity check remains enabled. Current metadata, source proofs and structured
parity judgments must be rebuilt before the full Desktop gate passes again.

## Durable local evidence

The logs listed above, the post-commit Desktop log, full-profile integration log,
final import wiring log and formatting log were copied to:

`/var/tmp/cordis-final-gates-p77rqmlc`

`SHA256SUMS` in that private directory binds their bytes. These are local run
artifacts, not substitutes for checked-in reproducible tests or final release QA.

## Native provider and tool-contract acceptance

Commit `7c69b5743` preserves authorized tool descriptions and input schemas through
ReAct, execution profiles, metering, failover and both HTTP model adapters. The
four affected crate suites passed 795 tests, and the server suite passed 607.
Strict Clippy remains nonzero on existing diagnostics at unchanged statements;
it is not reported as passing. The separate native-tool-contract document records
the regression boundaries and the failing test before the implementation.

The Electron client was rebuilt and launched through `make -C agi-stack run-desktop`
with the task-owned QA profile. Provider creation, environment-key connection
verification, rename, disable and re-enable succeeded. Disabling cleared the
route; the first attempt failed with `model_unconfigured`, then the route was
explicitly saved. Before the fix, actual model calls reached `submit_plan` with
invalid task fields and later timed out. Those failures remain in the evidence.

After the fix, a fresh `Cordis Tool Contract Native Acceptance` conversation
(`6b326d64-1236-5fde-b371-fc42e4598e14`) submitted a valid structured plan in a
real `kimi-for-coding` call. The single reviewed read-only step was approved in
the native UI. The model replied exactly `CORDIS_FINAL_NATIVE_KIMI_OK 437` and
the result was approved. A full application exit and canonical Make relaunch
preserved the plan, response and completed status.

The temporary `Cordis Final Kimi QA Updated` provider was removed through the
UI after restoring the original `Cordis Native Kimi QA / kimi-for-coding` default
route. Deleting it while it was still the default failed; switching the route
made the deletion succeed. The two original providers remain. No key value was
printed or written to the evidence; the credential source was an environment
reference. Native accessibility and screenshots are stored privately in
`/var/tmp/cordis-final-native-7TENNl`.

This establishes the provider lifecycle, actual model/tool operation and restart
persistence. The accessibility tree retained a stale loading placeholder for the
completed conversation. Direct inspection of both the original post-restart
screenshot and a later native screenshot showed the correct completed-run input
restriction. Temporary phase-only diagnostics also observed the request returning
in approximately 87 milliseconds and authority becoming ready. A proposed loading
lifecycle change was therefore withdrawn before commit; it is not counted as a
necessary native fix. The run summary's file counts reflect repository state and
are not evidence that this read-only arithmetic task edited files.

The separate historical database recovery document records a verified real backup,
restore and full upgrade of an isolated copy. The original database remains at its
old revision and has not been retired.

## Production retirement boundary review

Manual entry-point tracing found no production use of `AgentPluginRegistry`,
`PluginRuntimeApi`, `LegacyInventoryBridge` or `legacy-http-route-bridge`.
The authenticated legacy platform-plugin router is a fixed 410 tombstone; its
unknown V2 paths return 404. V1 package media types are rejected by the package
registry. Offline conversion code and historical documents are not runtime
compatibility paths.

Web `App.tsx` consumes artifacts projected by
`web/src/routes/v2/webRouteAuthorityStateV2.ts` from the current generation's
contribution registry. Desktop `App.tsx` consumes route/navigation registries from
`desktopRendererGenerationV2.state`; `desktopRendererAuthorityStateV2.ts` constructs
business routes from published route artifacts, retaining a separate authentication
kernel. The large App still supplies business bindings, but those bindings do not
constitute an independently owned route registry. Current polling entry points use
V2 Web-view or Desktop delivery contracts.

The reviewing agent's GitNexus MCP transport failed; a separate root CLI query was
available, but the index is not a complete current call-graph proof. This review is
explicitly a source-traced finding. The passing V2 directory includes the existing
retirement and route-ownership tests; native execution remains separately required.

Homebrew's keg-only `libpq@16` client tools were installed for the eventual
operational preflight. `/opt/homebrew/opt/libpq@16/bin/pg_dump` and `pg_restore`
report 16.15; the latter read the retained custom archive successfully. No service
was installed or started by this formula and no shell startup file was changed.
