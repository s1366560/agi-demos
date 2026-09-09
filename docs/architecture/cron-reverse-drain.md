# Scheduler reverse drain (Rust to Python rollback)

The reverse drain rolls a verified Rust delegation back to Python without ever
having two execution authorities. It is the explicit, operator-driven counterpart
of the [forward cutover barrier](cron-cutover-barrier.md). Nothing here is
automatic: every transition is a CLI command with a compare-and-swap revision,
and no command starts or stops a scheduler process.

## State machine, both directions

The global owner row carries `(owner_kind, cutover_phase)`:

```
forward:  (python|off, unverified) --prepare----------> (draining, prepared)
          (draining, prepared)     --observe----------> (draining, blocked)
          (draining, blocked)      --trusted verifier-> (rust, verified)     [future writer]
reverse:  (rust, verified)         --prepare-reverse--> (rust, prepared)
          (rust, prepared)         --observe-reverse--> (rust, blocked)
          (rust, blocked)          --complete-reverse-> (python, unverified)
```

`cutover_revision` increases on every mutation in both directions and is never
reset. A rollback leaves `revision > 0`, so the migration downgrade guard keeps
refusing to drop the barrier afterwards.

At every intermediate state there is at most one admission authority, and during
any drain there is none:

- Python legacy admission requires `owner_kind = 'python'`.
- Every Rust admission transaction (owner acquire/renew/current, control scope
  discovery and reconciliation, operation dispatch, scheduled fire) expands the
  unified verified-cutover predicate, which requires `owner_kind = 'rust'`
  **and** `cutover_phase = 'verified'` with a structurally valid verification
  receipt.
- During `(rust, prepared|blocked)` the phase is no longer `verified`, so all
  Rust admission fails closed in the preparation transaction itself, while
  Python admission stays closed because `owner_kind` is still `rust`.

## Reverse preparation

`prepare-reverse` locks the owner row, checks the expected revision, and
structurally mirrors the unified admission predicate before touching anything:
`owner_kind='rust'`, `cutover_phase='verified'`, revision >= 1, and a
`cron-deployment-verification.v1` block whose revision matches the row, whose
deployment id matches the persisted manifest, and whose receipt id, verifier id
and SHA-256 digests are well formed. It then records a `cron-reverse-drain.v1`
evidence section (deployment id, source/target owner kinds, database
preparation time) and sets `cutover_phase='prepared'`.

Closing admission does not abort in-flight work:

- Owner renewal fails the unified predicate, so the fenced owner's local
  capability is withdrawn and its supervisor attempts the exact release CAS.
  The release predicate intentionally does not check the phase, so cleanup
  still succeeds after revocation; a lease whose worker vanished expires and is
  reported as `active_rust_owner_lease = 0` once the database clock passes it.
- Already started executions keep their independent runtime leases and settle
  to a real terminal outcome or a durable `waiting_human` checkpoint. Queued
  runs, crash-interrupted runs with expired leases, retryable operations and
  pending HITL requests are durable resumable remainder — never abandoned
  mid-flight, and counted in the observation instead of being dropped.

## Drain observation

`observe-reverse` records a durable
[cron-reverse-drain-observation.v1](cron-reverse-drain-observation-v1.schema.json)
in the barrier and sets `cutover_phase='blocked'`. It is repeatable; each call
replaces the previous observation and increments the revision. The scan covers
the global scope conservatively — work that cannot be safely correlated to the
Rust deployment is counted rather than ignored:

| Count | Meaning | Blocks completion |
| --- | --- | --- |
| `active_rust_owner_lease` | Owner lease held and unexpired | yes |
| `live_running_runs` | `running` runs with an unexpired runtime lease | yes |
| `live_processing_operations` | `processing` operations with an unexpired dispatch lease | yes |
| `queued_runs` | Admitted, never claimed; durable and resumable | no |
| `interrupted_runs` | `running` with a lost lease; crash-resumable | no |
| `waiting_human_runs` | Parked with checkpoint and pending HITL | no |
| `retryable_operations` | `pending`/`failed` or lease-lost `processing` | no |
| `waiting_runtime_operations` | Awaiting runtime claim | no |
| `unresolved_hitl_requests` | `pending`/`answered` HITL requests | no |
| `retained_hitl_snapshots` | Retained HITL snapshots regardless of expiry | no |

The observation also records what drained since reverse preparation began:
`terminal_outcomes` (counts over `success`, `failed`, `timeout`, `cancelled`,
`skipped` for runs finished at or after the preparation time) and
`last_run_ids` (up to 50 most recent of those runs). These are diagnostics for
the operator, not an activation proof.

## Rollback completion

`complete-reverse` is allowed only after at least one recorded observation. It
re-runs the blocking scan **inside the completion transaction** — a stale
recorded observation cannot authorize rollback — and refuses while any
`active_rust_owner_lease`, `live_running_runs` or `live_processing_operations`
count is non-zero. On success it appends a
`cron-reverse-drain-completion.v1` record with the final observation, clears the
transient blocker diagnostics, sets `owner_kind='python'` and
`cutover_phase='unverified'`, and increments the revision.

The completion preserves the manifest, the append-only receipt log, the
verification receipt and the full reverse record. Python re-admission then
follows the exact same structural predicate as before the forward cutover
(`owner_kind='python'`); nothing is bypassed and nothing is deleted.

## Stale workers after rollback

A stale Rust worker that wakes after rollback has no write path left:

- Acquire/renew/current and every control, operation and scheduled-fire
  transaction require `owner_kind='rust'` **and** `cutover_phase='verified'`;
  the rolled-back row is `(python, unverified)`.
- Its exact release CAS no longer matches and degrades to a harmless no-op; it
  cannot mutate the rolled-back row.
- Run-scoped write-back (checkpoints, HITL parking, terminal projection) is
  fenced by the run's own runtime lease. Completion is gated on zero live
  runtime leases, so after rollback every stale worker's run lease is lost and
  the existing expired-worker rejection fails each write closed. The runs
  themselves remain durably resumable.

Likewise, automated rollback can never restore dual schedulers: re-establishing
Rust execution afterwards still requires the forward path from scratch — a fresh
`prepare`, real drain evidence and the future trusted verification writer.

## Operational commands

Run from the repository root with its configured database. `inspect` is the
read-only status command for both directions; its JSON now also carries
`drain_direction` (`forward`, `reverse` or `null`), `terminal_outcomes` and
`last_run_ids`. The mutating commands persist exactly what was requested.

```sh
PYTHONPATH=. uv run python scripts/cron_cutover_barrier.py inspect
PYTHONPATH=. uv run python scripts/cron_cutover_barrier.py prepare-reverse --expected-revision 4
PYTHONPATH=. uv run python scripts/cron_cutover_barrier.py observe-reverse --expected-revision 5
PYTHONPATH=. uv run python scripts/cron_cutover_barrier.py complete-reverse --expected-revision 6
```

Use the returned revision for the next mutation. There is no `force`, no
automatic timeout, and no command that skips the observation or the live
settlement re-check.

## Remaining work

- Resumable remainder (queued/interrupted runs, waiting HITL) survives rollback
  but is not claimed by the Python legacy dispatcher; it becomes executable
  again only through a future forward cutover. Operators must account for the
  recorded remainder before completing a rollback.
- Cross-deployment addressing and trusted source identities for the external
  verifier remain open on the forward path; the reverse path deliberately
  reuses the same persisted deployment identity instead of inventing a second
  trust domain.
- The drain observation is a point-in-time database scan. It is re-checked live
  at completion inside the same locked transaction, but it is not a proof about
  writers that bypass both admission fences (old binaries, direct SQL); those
  still require deployment control, exactly as on the forward path.

Tests use synthetic verifier receipts only inside private `qa_` schemas or
dedicated unmigrated test databases; the fixture helpers refuse to write such
evidence into a migrated shared schema. They validate protocol fencing, not
deployment readiness.
