# Native cloud sync connection and binding

The native connector keeps the local workspace session and the application's cloud
vault session separate. Cloud authentication uses the existing Electron authority.
These sidecar endpoints neither change the selected runtime mode nor hydrate a
cloud workspace into the local session. Production/default and local-only QA
profiles keep this route group closed; joint QA qualification is explicit.

All endpoints below are scoped POST requests under `/api/v1/knowledge/`, with the
normal native launch/session checks and `NativeKnowledgeScope`. Success uses the
existing `{contract_version, scope, result}` envelope. The JSON Schema in
`shared/schemas/knowledge/native-knowledge.v1.schema.json` generates Rust DTOs,
TypeScript DTOs and `nativeKnowledgeConnectionSchemaGenerated.ts` validators.

| Endpoint | Fields in addition to `scope` | Result |
| --- | --- | --- |
| `sync-connection` | None | `connection` projection or `null` |
| `sync-tenants` | `expected_connection_revision` | Connection and tenant `items` |
| `sync-projects` | Same, plus `tenant_id` | Connection, tenant and project `items` |
| `sync-enrollment` | Same, plus `project_id` | Connection and actual enrollment |
| `sync-enroll` | Same, plus `expected_generation` | Connection and enrollment |
| `sync-bind` | Same, plus `expected_generation` | Connection, enrollment, local `status`, `association_state: "verified"` |

The projection contains `connection_revision`, canonical API `authority` and actual
`actor_id`. The revision hashes a random authority-instance nonce, cloud vault epoch,
canonical origin and actor. It contains no credential or credential-derived data.
The renderer only echoes this observation for comparison. It cannot choose the
actor, URL, credentials, enrollment result or remote receipts.

Discovery reads the production `/tenants/` and `/projects/` schemas, with explicit
100-item pages and at most 10,000 items. Page number, page size, stable total,
completeness, duplicate identifiers and project tenant membership are checked.
Project discovery first verifies the requested tenant against the real membership
catalog. Binding independently rechecks `/auth/me`, the selected project, and its
enrollment; previously displayed catalog rows never grant authorization.

`expected_generation` is the full envelope returned by cloud enrollment:

```json
{"contract_version":"1.0.0","descriptor":{"profile_id":"observed profile","generation":81,"digest":"64 lowercase hexadecimal characters"}}
```

The actual generation is checked against the separately compiled cloud QA template
at that generation. Enrollment and subsequent data requests send the cloud
`X-Memstack-Knowledge-Sync-Generation` conditional header. A generation mismatch
fails with HTTP 412 and `knowledge_sync_cloud_generation_mismatch`. It does not
retry an external write. See `cloud-knowledge-sync-generation.md` for the server
request-pin contract. Consecutive HTTP requests do not share a server lease.

Binding requires enabled enrollment, an exact observed generation, and fresh local
and cloud authority. A single SQLite IMMEDIATE transaction persists the immutable
remote actor/tenant/project tuple and canonical origin in the existing link/target
tables. Local auth, native generation and cloud vault locks fence that transaction;
time deadlines are rechecked after acquiring storage and before commit.
Identical bindings replay; any different identity or origin conflicts. There is no
implicit rebinding or outbox identity migration.

The old `sync-link` endpoint remains an unverified association intent. It cannot
make a target eligible for data transport. Push, pull and conflict operations
require a previously bound exact origin and recheck active cloud identity,
project, enabled enrollment and qualified cloud generation. The `verified`
binding result records the successful verification at binding time; it does not
promise permanent cloud authorization or a persistent remote generation lease.

If enrollment commits but its response is lost, refresh `sync-enrollment` to
observe the real state. No local binding is created by enrollment itself. Cloud
logout, rotation or expiry invalidates pending observations; a local scope,
permission or generation change prevents a pending bind from committing.

The native Local Knowledge page exposes a separate Cloud connection card. Its
password login and forced password change use token-free Electron commands. The
card never calls cloud-session hydration or changes the local runtime, tenant,
project, actor or workspace. Mounting reads the existing cloud vault projection;
it does not sign in, enroll or bind. Users explicitly choose observed catalog rows,
enroll when authorized, and bind the enrolled target before push or pull is enabled.
A remounted card requires a fresh observation and explicit binding confirmation.

Authentication attempts have a main-process revision and serialized vault writes.
Disconnect, a newer login and local-authority exit retire older responses. A remote
signout response cannot clear a newer login. The main process exposes only a
credential-free authentication status so forced password change survives renderer
owner retirement during a vault write. Renderer unmount discards its UI requests;
the existing host authority transition remains responsible for local-runtime exit.
