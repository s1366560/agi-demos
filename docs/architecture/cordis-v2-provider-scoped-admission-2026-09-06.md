# Cordis V2 Provider scoped admission

Provider `chat.send` now authorizes before conversation creation and acquires a SESSION scoped reservation before entering the Agent turn. The HTTP Provider service-token boundary remains required; a supplied actor or scope is not itself membership evidence.

`WorkspaceProviderAdmissionV2` checks persisted Project tenant ancestry, UserTenant and UserProject membership, then Workspace Core membership and the exact returned workspace/tenant/project identity. Missing or failed authority checks cannot initialize a profile or acquire a lease. Existing conversation identity checks remain in the Provider adapter. Admission rechecks authority before preparation and after preparation before acquiring the durable admitted reservation.

Production startup passes a deferred app-state scoped-runtime lookup into the Workspace Core factory. ROOT resource construction does not eagerly require the later scoped application manager. Factories without this dependency cannot execute Provider turns. The scoped operation explicitly uses the reservation rather than inheriting the outer Provider ROOT reservation.

Duplicate deliveries reauthorize but retain terminal replay and avoid another preparation/acquisition. Tests verify denied authorization causes no conversation creation or correlation write; real scoped registry coverage verifies generation selection under an outer ROOT operation and release.

## Validation

- 54 focused tests passed, 21 warnings, 23.43 seconds: real SQL admission, Provider event/duplicate/terminal behavior, factory wiring, Workspace prompt context services.
- Pyright: 0 errors, 0 warnings for the three changed production service/adapter modules.
- Ruff, generated protocol check and contract completeness check passed.
- Logs and SHA256SUMS: `/var/tmp/cordis-provider-scoped-_mc61bol`.

## Remaining scope

These are point-in-time authorization checks, not a continuous revocation fence. Remote Core responses are mocked in admission tests; this batch is not live Core or native model acceptance. Provider history/control/injection and other consumers require their own authorization and scoped-runtime audit. ROOT legacy migration, historical full migration-chain recovery, final V1 retirement, parity rebinding and final native acceptance remain open.
