# Cron control owner lifecycle

The Rust scheduler retains one global owner generation across control polls. A
separate cooperative task renews its lease while the scheduler is idle, performing
control work, or awaiting an admitted Agent execution. Renewal runs every third of
the owner TTL and has a deadline of another third. These durations are protocol
limits, not evidence that a deployment drained.

The scheduler checks the locally published capability before each new page, control
scope and runtime scope. Renewal failure, timeout, invalid generation or shutdown
withdraws that capability and attempts exact database release. An already started
driver future is allowed to settle; neither owner loss nor cancellation of a caller's
`shutdown()` aborts it. The generation keeps its resources until that future ends.
Dropping the scheduler runtime also requests owner-task shutdown, preventing an
orphan heartbeat from retaining control indefinitely after a driver panic.

## Stable generation and lease snapshots

Control admission requires the same global scope, owner id, epoch and nonce. The
database expiry must be at least the caller's snapshot expiry and must exceed both
the supplied observation and PostgreSQL `clock_timestamp()`. Thus normal renewal
does not invalidate work using a prior snapshot of the same generation, including
when that snapshot's original expiry has elapsed. A future expiry that was never
issued, a different epoch or nonce, a DB-expired lease, or a revoked cutover remains
fenced. Local expiry alone cannot determine whether another task renewed the owner;
the control repositories remain authoritative.

Renewal and release keep exact snapshot compare-and-swap checks. Neither can use a
pre-renewal snapshot to mutate the current row. If a timed-out database renewal has
an uncertain commit, cleanup may fail its exact match; local admission stays closed
and the database lease must expire or be settled through the existing control plane.
This does not authorize reverse delegation.

## Execution and deployment boundaries

Operation dispatch leases and runtime execution leases remain independent. A real
Agent execution continues its own heartbeat after control owner loss and records
its actual terminal outcome. An execution awaiting a human persists its checkpoint
and pending request without a fabricated `finished_at`. A subsequent driver can
consume the persisted answer and finish that same run.

Releasing a local control lease is not deployment drain evidence. The
[deployment cutover barrier](cron-cutover-barrier.md) still requires external,
authenticated proof of old producers, queues, ordinary executions and HITL resume
authorities. This change supplies no verification writer, backward delegation,
automatic activation or production-gate override. Full deployment cutover and
reverse drain remain blocked without those external boundaries.

## Verification

- Runner tests retain one owner across idle polls, renew during blocked control and
  runtime work, and stop new scopes on loss while active work settles.
- Generation tests cover replacement, cancellation of drain, resource isolation
  and stale-generation release against private PostgreSQL state.
- Private PostgreSQL control/fire/operation tests exercise old renewed snapshots,
  invalid expiry/epoch/nonce, database expiry with a stale application observation,
  cutover revocation, and unchanged exact renewal/release CAS.
- A private PostgreSQL test drives the released ReAct runtime through a blocked
  pure tool. It revokes control ownership, observes continued independent run
  heartbeats, cancels drain, then verifies actual Agent completion or durable HITL
  suspension and recovery from a persisted answer.

Synthetic test verification receipts establish only the test protocol boundary;
they are not deployment readiness evidence.
