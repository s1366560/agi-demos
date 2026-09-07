# Protocol V2 Capability Inventory

This document describes ownership categories. It is not a manually maintained module inventory.
Exact module, service, event, scope, target, version, artifact, and digest records come from the
generated V2 catalog and graphs linked below.

## Generated authority

- `shared/catalogs/plugin-module-catalog.v2.json`
- `shared/graphs/plugin-service-dependencies.v2.json`
- `shared/graphs/plugin-events.v2.json`
- `shared/profiles/memstack-default-bootstrap.v2.json`

Run `make plugin-v2-contract-gate` after changing a manifest, Profile, contract, or runtime effect.

## Capability ownership

| Area | V2 ownership | Typical scope | Targets |
| --- | --- | --- | --- |
| Agent loop, prompts, tools, skills, subagents, definitions, hooks | Explicit service/event effects resolved per pinned turn | tenant/project/session | Python |
| Session event log and replay | Ordered generation-owned service | session/operation | Python |
| Persistence, tenant, project, transaction factories | Repository/service effects; request DB session remains a kernel resource | root/tenant/project | Python |
| Memory, graph, retrieval, model/provider adapters | Versioned provider and resolver services | tenant/project/session | Python |
| Sandbox, MCP, channels, workflow, background tasks | Runtime/service effects with typed events and disposers | project/session | Python/Rust/sidecar |
| HTTP routes and OpenAPI | Route contributions mounted by the generation-aware dispatcher | root/tenant/project | Python |
| Routes, navigation, UI slots | Renderer contributions resolved from target artifact catalogs | renderer generation | Web/Desktop |
| Telemetry | Generation-owned runtime service; exporters remain permission constrained | root/tenant | Python/Rust |
| Bundle/Profile/Marketplace/HMR | Desired Bundle Set plus complete candidate generation | root/tenant/project/session | control plane/all targets |
| Publication receipts/readiness | Immutable publication roster and per-target ACK/NACK | deployment | control plane/all targets |

## Non-plugin kernel

These surfaces are never replaceable by tenant or untrusted plugins:

- authentication and tenant/project authorization;
- Alembic migrations and database schema authority;
- vault encryption, secret grant issuance, and credential redaction;
- sandbox and process-boundary enforcement;
- Loader/Fiber/generation leases and contract verification;
- V2 publication, receipt validation, readiness aggregation, and audit persistence.

Trusted builtins may expose observations or adapters for these surfaces, but they cannot replace the
enforcement authority.

## Trust and isolation

Builtin and verified signed artifacts may run only in their declared target and isolation mode.
Tenant-approved or untrusted code must use an isolated Wasm, MCP, or subprocess boundary and cannot
receive raw vault secrets. Renderer contributions are resolved from an allow-listed target artifact
catalog; unknown module or artifact references NACK the candidate generation.
