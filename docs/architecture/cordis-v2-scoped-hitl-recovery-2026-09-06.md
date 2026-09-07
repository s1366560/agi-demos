# Cordis V2 scoped HITL and subscription recovery

HITL response publication, HITL recovery admission and subscription recovery now acquire the existing admitted SESSION runtime and explicitly pin its reservation. They do not prepare or publish a new configuration and do not inherit a ROOT connection generation. The Agent service roots now include the recovery-stream resolver, validated against the production contracts and real scoped Loader.

`scoped_session_admission_v2` checks persisted conversation scope, Project tenant ancestry and both tenant/project membership. Ordinary subscription requires conversation ownership before subscribing. An explicitly targeted HITL request preserves the existing designated-recipient behavior: its persisted request ID, conversation, tenant, project, status and recipient must match. An unassigned HITL request requires conversation ownership. The request ID is passed into the detached recovery task for another database authorization check before resolving or consuming the stream.

Recovery retains its exact generation through the existing operation fork. Duplicate bridge admission, cancellation before task start, caller cancellation and normal completion retain their lease cleanup behavior. Tests use distinct ROOT and scoped resources, replace the scoped generation during recovery, and verify the old generation drains only when its held reservation/fork is released.

The single-winner HITL response commit still precedes Redis delivery. A failed delivery preserves the answered response and the delivery-pending behavior. Encrypted response serialization remains in use.

## Remaining gates

An unadmitted session fails closed; historical session reconstruction and full restart recovery remain open. Authorization checks are point-in-time checks, not a continuous revocation fence. Actor/worker consumers, legacy ROOT migration, historical full migration-chain recovery, final V1 retirement, parity rebinding and native acceptance still require completion. This batch does not claim a live external Redis or model operation.

## Validation

- Final combined WebSocket directory, subscription scoped authority and production service-root Loader tests: 160 passed, 21 warnings, 82.16 seconds.
- Real SQL existing-session and targeted-HITL admission tests: 17 passed (included in the combined run).
- Pyright: 0 errors, 0 warnings for the three production admission/handler modules. Ruff, protocol generation and contract completeness checks passed.
- Durable logs and SHA256SUMS: `/var/tmp/cordis-hitl-recovery-0l0us848`.
