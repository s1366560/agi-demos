# Background consumption begins after ROOT publication

The real scheduler ownership rerun completed shutdown successfully, but exposed a
startup race. Skill Evolution staged its process scheduler and scheduled the first
tenant sweep before the ROOT host had been installed. Its configuration lease
correctly failed with `process_generation_host_not_configured`. Increasing the
startup delay would not establish the required publication order.

Skill Evolution now builds a paused candidate during staging. Each generation
provides a facade with its own token; registered and activated tokens are tracked
separately. An unadmitted facade cannot consume through an older generation's
running scheduler. Activation requires an active operation resolving that exact
facade from its own generation. Retiring the last activated generation stops the
scheduler even if a paused candidate remains registered.

The Host has an explicit, initially disabled post-admission callback. ROOT startup
enables it only after persistence and process-host installation. Accepted apply,
receipt retry and pending-request supersession then share the same activation
path. Scoped and remote hosts do not automatically start process consumers. The
callback runs under a short generation lease without reentering the Host lock or
retaining the lease in background tasks. Repeated successful activation of the
same generation is skipped. Activation failure retains the real publication
outcome for idempotent receipt recovery and fences new admission.

The ROOT callback creates an operation for activation only; it does not bind that
operation into a background task's context. Normal work continues to acquire its
own configuration, repository and model leases.

## Validation

- Real Loader tests first demonstrated consumption during staging. The revised
  Skill Evolution tests passed all 12 cases in 45.29 seconds.
- Eight new Host activation tests plus 19 receipt/supersession regressions passed:
  27 total, including failed staging, receipt ordering, activation failure,
  idempotence and a cancelled observer.
- The existing Host suite passed all 28 tests. An older startup fixture failed
  before reaching the new callback because its real ACK had never been persisted.
  The fixture now stores that already-produced ACK. All eight startup tests and
  seven restore-fence tests then passed in 215.05 seconds; unreceipted requests
  still fail closed. No production recovery guard was weakened.
- Ruff passed. Pyright reported zero errors; four existing Host warnings concern
  unchanged constructor and context-manager statements.
- The modified Python artifact digest was recomputed from its actual bytes, and
  the canonical generator rebuilt all five catalog/bootstrap outputs. Generation
  consistency and contract completeness checks passed. Public service contracts
  and snapshot entries did not change.

Direct tracing covered the shared receipt retry and supersession
Host path, HTTP coordinator, marketplace recovery and the separate scoped receipt
coordinator. No activation was inserted in the earlier HTTP on-commit callback.

Logs use the private `/tmp/cordis-skill-evolution-activation-`,
`/tmp/cordis-host-activation-` and `/tmp/cordis-startup-receipted-fixture-` prefixes.
The original real startup race is preserved in
`/var/tmp/cordis-final-retirement-ufhyv7hu/scheduler-fixed-startup-race-api.log`.
The final acceptance record documents the subsequent content-addressed ROOT
configuration rollout and actual clean startup/shutdown.
