# Platform Plugin Kernel V2

## Decision

MemStack uses a protocol-v2 capability kernel while retaining FastAPI, Rust, React, Electron,
Ray, and the existing security boundaries. Production composition is V2-only: every business
capability enters a target through an explicit module contract and an ordered Profile entry.
Protocol-v1 profiles, snapshots, discovery, route bridges, and mutation APIs are retired.

The kernel is deliberately small. It owns only:

- Loader/Fiber/generation lifecycle and immutable generation leases;
- authentication, authorization, tenant/project isolation, and permission enforcement;
- Alembic schema authority and transaction boundaries;
- application vault, secret grants, sandbox enforcement, and trust verification;
- protocol-v2 publication, receipt/readiness aggregation, and append-only audit records.

The kernel does not implement dynamic Host+Client self-modification packages such as
`inspect/define/run/stop`.

## Authoritative contracts

The generated V2 artifacts are the source of truth:

| Authority | Path |
| --- | --- |
| Shared protocol schema | `shared/schemas/plugin-protocol-v2.schema.json` |
| Module declarations | `config/plugin-manifests-v2/*.v2.json` |
| Ordered default composition | `config/plugin-profiles/memstack-default.v2.yaml` |
| Target module catalog | `shared/catalogs/plugin-module-catalog.v2.json` |
| Service dependency graph | `shared/graphs/plugin-service-dependencies.v2.json` |
| Typed event graph | `shared/graphs/plugin-events.v2.json` |
| Cross-language fixtures | `shared/fixtures/plugin-protocol-v2/` |

`scripts/generate_plugin_protocol_v2.py` generates Python, Rust, and TypeScript protocol/catalog
surfaces from those declarations. `make plugin-v2-contract-gate` rejects missing declarations,
stale output, digest drift, undeclared service/event use, and target-catalog gaps.

## Contract and injection model

Each module publishes an exact `contract` containing:

- versioned services it provides and requires;
- typed events it emits and handles, including fixed dispatch mode and JSON Schemas;
- a JSON Schema 2020-12 configuration contract;
- a canonical `contract_digest`.

`PluginDefinitionV2` contains only `module_ref`, `contract_digest`, and `apply`. The Loader verifies
manifest, generated catalog, artifact, and runtime definition digests before executing an
entrypoint. Consumers receive declared aliases from the active Profile; they do not import or name
provider implementations.

Providers are unique by service key, version, scope, and isolation. Required services never use an
implicit builtin fallback. Optional behavior is represented by a separate Profile entry.

## Scope and lifecycle

The persistent scope tree is `root -> tenant -> project -> session`. Request, turn, and operation
work use `OperationContextV2` beneath a pinned generation. Every effect registers a disposer.
Candidate failure and normal shutdown release effects in LIFO and reverse dependency order.

HTTP requests, agent turns, WebSocket sessions, Rust/sidecar operations, and renderer boundaries
hold immutable generation leases. A new generation can be selected only at a new boundary; one
operation never mixes generations.

## Profiles, Bundles, and HMR

Composition order is deterministic:

1. base Bundles in declaration order;
2. Profile;
3. tenant overlay;
4. project overlay;
5. session overlay.

A duplicate entry is invalid unless the later layer explicitly uses `replace` or `disable`.
`.mspkg` archives contain only V2 manifests, target artifacts, layers, digest/signature, and
provenance. Marketplace changes update `DesiredBundleSetV2`; they never write a V1 YAML profile.

HMR builds a complete candidate generation, verifies every artifact and contract, activates every
Fiber, and runs health checks before an atomic local switch. Any failure produces a NACK, disposes
the entire candidate, and leaves the target's last-good generation unchanged. Module-level in-place
patching is not supported.

## Publication and readiness

Each immutable publication records a finite `required_data_plane_ids` roster and ACK deadline.
Receipts bind the publication nonce, registered data-plane ID, and exact version/digest. Status is
`reconciling`, `ready`, or `degraded`.

Targets switch independently. A NACK or timeout keeps that target on its own last-good generation;
other ACKed targets continue on the new generation. Late valid ACKs can converge a degraded
publication to ready. Administrators roll back by creating a new audited publication from the most
recent globally-ready snapshot; the control plane does not silently roll back all targets.

## Target composition

- Python/FastAPI obtains routes, repositories, services, agent capabilities, background tasks, and
  lifespan resources from V2 effects.
- Rust server and desktop sidecar validate a generated non-empty target catalog and NACK unknown or
  mismatched modules.
- Web and Desktop renderer roots retain only authentication/error/generation hosting; business
  routes, navigation, and UI slots come from `@agistack/plugin-runtime` contributions.
- Agent turns resolve the complete service set from their pinned generation and rebuild
  model-visible state from the ordered session event log.

## Protocol-v1 retirement

Known V1 HTTP paths return `410 plugin_protocol_v1_retired`. Unknown `/v2/*` descendants remain
normal 404s. V1 packages and schemas are incompatible and are not converted at runtime. The only
supported desired-state conversion is the audited offline workflow documented in
`plugin-protocol-v1-to-v2-conversion.md`.
