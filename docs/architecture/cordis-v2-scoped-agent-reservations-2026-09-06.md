# Scoped Agent generation reservations

Scoped publication admission now returns a reservation containing its exact scope,
host incarnation and acquired generation lease. The coordinator retains its database
head lock, latest/last-good receipt checks and local descriptor validation. Existing
lease-only callers delegate to this admission path. The lower registry API remains
an internal lifecycle capability; it does not authenticate or prove durable admission.

The captured host resolves distributions and retains exact generations directly on
its original host. Closing and recreating the same scope cannot redirect an old
operation to the replacement, even when their descriptors are identical. New current
leases are rejected on retired hosts, including retirement while acquisition awaits;
exact retention of a still-leased old generation remains valid.

`pin_scoped_agent_turn_operation_v2` consumes a reservation once, checks the complete
authenticated session scope, binds both generation and host contexts, and restores
outer contexts on exit. It does not inherit the surrounding HTTP operation. Caller
services cannot override the admitted distribution. Setup failures and cancellation
release the acquired lease; duplicate consumption cannot release another active use.

The shared distribution reader now uses the bound host instead of the process ROOT
fallback. Parent distribution reuse requires the same generation object and descriptor.
Existing detached Agent operations therefore retain the correct scoped host through
scope retirement and recreation without introducing another distribution cache.

The authenticated source-to-publication integration test now enters this boundary and
forks a child operation after durable receipt admission. Its provider remains a test
conformance provider. This proves configuration consumption and operation ownership,
not production Agent startup, LLM execution or native acceptance.

Production Agent entry points still require authenticated admission wiring and scoped
definition factories with correct tenant/resource ownership. Stage 6, historical full
migration-chain recovery, V1 retirement and final native acceptance remain incomplete.

Validation: final combined regression passed 46 tests; existing runtime host regression
passed 28 tests; real isolated PostgreSQL regression passed 13 tests and cleaned its
container. PostgreSQL validation covers the established migration slice, not the full
historical chain. Protocol generation/check and contract completeness passed; Ruff
and diff whitespace checks passed. Evidence SHA-256 inventory: `/var/tmp/cordis-scoped-agent-reservations-v_lf5xat`.
