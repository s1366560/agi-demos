# Cordis V2 scoped control authority

Provider history, inject and abort now invoke the same local membership and Workspace Core authorization service as chat.send, before obtaining repositories or cancelling execution. Existing persisted conversation identity checks remain required. These operations do not initialize or publish an Agent configuration.

WebSocket steer and kill_run now acquire the admitted SESSION reservation from the application scoped runtime manager. The control operation uses that reservation explicitly instead of inheriting a ROOT connection generation. Admission requires conversation ownership, tenant membership, project membership and matching Project tenant ancestry. Existing run revision, active state, participant roster, command receipt and idempotency checks still precede dispatch.

Control commands do not prepare a new profile or replace the current publication. If a scoped runtime has not been recovered or admitted, the command returns control_authority_unavailable. Recovery of historical sessions remains a separate required gate. This change does not claim transactional protection against permission revocation after the SQL check.

HITL publishing and subscription recovery still have ROOT operation consumers and remain open migration work. Provider cancellation still targets the existing Ray/local execution substrates. This batch does not constitute final native acceptance, full V1 retirement or migration-chain validation.

## Validation

- WebSocket directory: 132 passed, 21 warnings, 38.22 seconds.
- Provider and real SQL admission combination: 47 passed, 21 warnings, 12.70 seconds.
- Scoped control and Redis reload tests: 8 passed, 21 warnings, 15.85 seconds. These overlap the directory run and are not additive.
- Real scoped registry tests use ROOT without Redis and scoped Redis generations, retain the old reservation through reload, and verify release and absence of static fallback.
- Pyright: 0 errors, 5 existing control-handler warnings (model field overrides, unknown JSON return, missing override annotations). Ruff and protocol generation/completeness checks passed.
- Evidence and SHA256SUMS: `/var/tmp/cordis-control-scoped-5s9edyrk`.
