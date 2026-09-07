# Protocol V2 Runtime Coverage Matrix

This is the production acceptance view for full pluginization. Generated catalog/graph artifacts are
the exact inventory; this table records the composition boundary each runtime must prove.

Status legend:

- **V2 authority** — the production path is resolved from a pinned V2 generation;
- **kernel** — deterministic security/protocol authority intentionally remains in the host;
- **retired** — V1 path returns 410, is incompatible, or has no production reference.

| Surface | Python API/agent | Rust server | Desktop sidecar | Web renderer | Desktop renderer |
| --- | --- | --- | --- | --- | --- |
| Contract/catalog validation | V2 authority | V2 authority | V2 authority | V2 authority | V2 authority |
| Generation lease and last-good | V2 authority | V2 authority | V2 authority | V2 authority | V2 authority |
| Services and scoped injection | V2 authority | V2 authority | V2 authority | target host | target host |
| Typed events and fixed modes | V2 authority | catalog validation | catalog validation | contribution lifecycle | contribution lifecycle |
| Agent loop/tool/skill/subagent/hooks | V2 authority | target capability only | target capability only | n/a | n/a |
| Persistence/domain services | V2 authority | target-local services | target-local services | n/a | n/a |
| HTTP/local routes | V2 authority | V2 target catalog | V2 target catalog | n/a | n/a |
| Business route/navigation composition | n/a | n/a | n/a | V2 authority | V2 authority |
| UI slots | contribution source | n/a | local capability | V2 authority | V2 authority |
| Bundle/Profile/HMR | V2 authority | candidate activation | candidate activation | candidate activation | candidate activation |
| Publication ACK/readiness | control-plane authority | exact receipt | exact receipt | ephemeral unless rostered | ephemeral unless rostered |
| Authentication/tenant/vault/sandbox | kernel | kernel | kernel | kernel client boundary | kernel client boundary |
| V1 profile/snapshot/discovery/poller | retired | retired | retired | retired | retired |

## Required evidence

1. `scripts/generate_plugin_protocol_v2.py --check` leaves the worktree unchanged.
2. Python, Rust, and TypeScript accept/reject the same conformance fixtures.
3. Candidate failure proves LIFO cleanup and preserves each target's last-good generation.
4. Agent turn/session replay records and reuses an immutable generation descriptor.
5. FastAPI route/OpenAPI parity and tenant/transaction/lifespan tests pass from V2 contributions.
6. Rust server, sidecar, Web, and Desktop each activate a non-empty local target module set.
7. ACK aggregation covers idempotency, stale/forged/unregistered receipts, timeout, late recovery,
   ephemeral exclusion, and explicit republish-last-ready.
8. Production source has no V1 registry, bridge, snapshot/poller, or static business route/nav
   authority.
9. Native QA starts with `make -C agi-stack run-desktop` and completes a provider-backed operation
   through the application vault or environment without exposing credentials.
