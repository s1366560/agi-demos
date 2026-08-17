# Platform Plugin Kernel

## Decision

MemStack adopts a platform capability kernel instead of porting Cordis or rewriting the
Python service in TypeScript. The kernel keeps the current FastAPI, Ray, React, Electron,
and Rust deployment surfaces while making capability ownership declarative and reversible.

The implementation is split into four contracts:

1. A pure manifest model in `src/domain/model/plugins`.
2. A reversible `PluginContext` and `CapabilityRegistry` in `src/infrastructure/plugins`.
3. A profile composer that emits canonical, digest-stable JSON snapshots.
4. A Rust serde contract in `agi-stack/crates/plugin-host/src/snapshot.rs`.

The legacy agent plugin registry remains the Phase 1 compatibility facade. The new
`unregister_plugin` operation removes only one plugin's owned registrations, and the
built-in registration bridge records the same capabilities in both generations before
returning a single disposer.

## Trust and runtime boundaries

| Runtime | Allowed trust | Enforcement |
| --- | --- | --- |
| `python-trusted` | builtin or signed | Same process only for first-party packages. |
| `wasm` | signed, tenant-approved, untrusted | Rust Wasmtime on server/desktop; platform fallback elsewhere. |
| `mcp` | signed, tenant-approved, untrusted | Protocol access only. |
| `subprocess` | signed, tenant-approved, untrusted | Process boundary and protocol access only. |
| `frontend` | signed, tenant-approved, untrusted | UI slots/renderers only; no server secrets. |

`agent_loop` and `credential_source` are kernel capabilities and can only be claimed by a
builtin manifest. Tenant plugins may implement ordinary providers and consumers, but cannot
replace authentication, authorization, migrations, tenant isolation, or the credential vault.

Secrets are not passed through `PluginContext`. A context exposes authorized references
such as `vault://...`; an execution boundary owned by the host resolves the value with the
least privilege required.

## Capability ownership

A capability is identified by:

```text
(plugin_id, capability_kind, capability_id)
```

Registrations are effects. Every context registration returns or retains a disposer, and
`close()` releases effects in reverse acquisition order. Default registrations are
plugin-namespaced so multiple runtime plugins can expose hooks with the same event name.
A subsystem can choose a singleton key when exactly one active provider is required.

Manifest capability contracts are plugin-owned (`contract@plugin_id`) for dependency checks.
This preserves multiple observers on the same hook contract while making a required provider
contract unique to its owning plugin.

## Profile composition

`config/plugin-profiles/memstack-default.yaml` is the first declarative default profile.
Rows have stable plugin ids. A patch addresses a row id and replaces the complete config;
it never deep-merges. Later layers and patches win.

The composer:

- rejects unknown manifest ids and unknown patch targets;
- validates whole-row configuration against declared JSON Schemas;
- validates requirements and minimum versions;
- rejects dependency cycles;
- orders providers before consumers;
- computes a SHA-256 digest over canonical JSON.

A control-plane envelope carries `version`, `nonce`, `snapshot_digest`, and `type_url`.
Data planes retain their last-good snapshot on NACK. Control flow carries the envelope;
LLM tokens, tool I/O, and retrieval payloads stay on the data path.

## Persistence

The first control-plane migration adds:

- `platform_plugin_catalog`: authoritative manifests.
- `platform_plugin_desired_states`: scoped desired activation/config and revisions.
- `platform_plugin_snapshots`: immutable effective profile snapshots.
- `platform_plugin_capability_audits`: append-only capability ownership transitions.
- `platform_plugin_apply_states`: latest ACK/NACK version per data plane.

Repositories never commit. Endpoint or scheduler callers own the transaction and commit
after desired state and audit records are consistent.

## Phase map

| Phase | Status in this change |
| --- | --- |
| 0 capability inventory and architecture decision | Implemented as an architecture contract and inventory. |
| 1 reversible kernel and legacy facade | Implemented for capability ownership and trusted builtins. |
| 2 profile/control-plane foundation | Implemented for composition, persistence, snapshot envelope, and Rust contract. |
| 3 agent runtime migration | Ports, typed event bus, tool generation cache, prompt/subagent/loop contracts implemented. Legacy processor and tool cache cutover remains incremental behind feature flags. |
| 4 provider/channel/storage migration | Provider route/credential lease, channel/backend/HTTP route contracts, desired-state tables, and route mount service implemented. Existing manager/router cutover remains incremental. |
| 5 Rust, desktop, and Web UI surfaces | Rust full-profile reconciler with ACK/NACK and last-good, desktop builtin UI slot registry, and generated platform capability inventory implemented. Native sidecar wiring and external renderer loading remain future work. |
| 6 external ecosystem and hardening | Ed25519 package verification, SLSA provenance checks, permission gate, quota accounting, package/revocation persistence, and pure marketplace decisions implemented. OCI distribution and public catalog remain future work. |

Full migration remains deliberately incremental. Every phase must preserve the current
default behavior when the new profile has no active external plugins.
