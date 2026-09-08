# Native project schema RPC v1

This boundary exposes explicit local portable-schema operations. It does not
activate a production schema service, add synchronization or enrollment, import
legacy schemas, or interpret the meaning of names or opaque schema definitions.
Production admission remains closed for the default, local acceptance, and sync
acceptance profiles. Positive execution is restricted to test-only internal
validation. Existing Memory action rosters do not grant schema actions.

`native-rpc.schema.json` is the RPC source. Its document reference resolves to
`document.schema.json`; its operation scope resolves to the existing canonical
`NativeKnowledgeScope`. Run `python3 scripts/generate_native_project_schema_contract.py`
to regenerate Rust request DTOs/action metadata and TypeScript types/validators'
closed schema data. Run it with `--check` to detect drift.

| Method | Path suffix under `/api/v1/knowledge/schema` | Request body |
| --- | --- | --- |
| POST | `/read` | `scope` |
| POST | `/bootstrap` | `scope`, `change_id`, `expected_revision: 0`, full `document` |
| POST | `/replace` | `scope`, `change_id`, positive `expected_revision`, full `document` |
| POST | `/receipt` | `scope`, `change_id` |
| POST | `/history` | `scope`, `after_revision`, `limit` (1–100) |
| GET | `/capabilities` | No body |

Scope asserts the authenticated tenant/project/context revision and admitted
profile/generation/digest. Context revision zero is valid for an initial context.
Actor identity comes from the live native session; it is never a request field.
Every operation is bound to one dedicated schema action and repeats live session,
membership, generation, and action admission. A viewer may read and query history
or its own receipts, but cannot submit or replay a previously authorized write.

Mutation CAS and replay identity come exclusively from the body. Query strings,
unknown fields, duplicate object keys, and Memory mutation headers
(`Idempotency-Key`, `X-Expected-Revision`, `If-Match`, `If-None-Match`) are rejected.
The raw document reaches the core parser without an intermediate JSON Value, so
integer token and duplicate-key validation remains effective. Protocol counter
`-0`, decimal, and exponent tokens are rejected; opaque schema numbers retain the
portable document's independent finite/safe-number rules.

Bootstrap is explicit creation of revision 1 without historical tombstones.
Replace submits the entire next adjacent snapshot, preserving the schema identity
and all required tombstones. It is not a cloud typed patch. Reads never create a
schema or select defaults; an absent document or receipt is represented by null.

Successful reads, first writes, and replays return HTTP 200. Every response has
`contract_version: "1.0.0"`, `authority: "native-project-schema"`, the exact
`operation`, authenticated `actor_id`, current asserted `scope`, and `result`.
Mutation and receipt responses contain one complete original persisted receipt;
they do not reconstruct acceptance from the current head. A current scope envelope
may legitimately change after a new authenticated context/generation, while the
persisted receipt remains exact. Changing the original command under a reused
change ID is a conflict, including a changed submitted member-array order.

Requests and complete responses are bounded to 2 MiB; documents are bounded to
1 MiB and to the portable document weight limit. Mutation response serialization
uses the actual receipt and scope envelope inside the same validated write
transaction, before commit, including replay. A rejected preflight rolls back a
new head and journal entry. Accepted bytes are cached and returned without a
second serialization or head read.

History returns `schema_id`, requested `after_revision`, snapshot `upper_revision`,
`next_after_revision`, `has_more`, and a contiguous prefix of complete receipts.
Schema identity, upper revision, and prefix are obtained in one SQLite read
transaction. The byte budget reserves the upper revision's digit width and the
longer `false` spelling. Iteration stops before the first whole receipt that would
exceed the reply budget; it does not materialize 100 maximum-sized documents.
The next cursor is the final returned revision, or the unchanged input cursor
when empty. An absent schema has null identity and zero revisions. A cursor above
the observed upper revision conflicts.

The separate capability response identifies `project-project-schema`, reports
observed sidecar provenance, and lists only the dedicated schema action roster.
The standalone TypeScript factory requires both an authority-owned capability
getter and a current-operation lease guard. Each command and expected scope is
cloned and frozen before any await. Actor/context are observed before and after
the schema request, and capability/lease checks surround every asynchronous
boundary. No automatic mutation retry, rebase, ID default, or import is performed.
There is no production renderer service binding in this change.

The schema-only transport reuses the native credential/request helpers. It
rejects redirects, counts streamed UTF-8 bytes before decoding, rejects duplicate
JSON keys before value validation, cancels failed response readers, and releases
reader locks. Memory transport behavior is unchanged.

| HTTP status | Condition |
| --- | --- |
| 400 | Malformed JSON syntax |
| 401 | Existing native launch/session middleware rejection |
| 403 | Live authorization or asserted tenant/project scope rejection |
| 409 | Generation, CAS/cursor, or change-ID reuse conflict |
| 413 | Request, raw document, or complete reply byte limit |
| 422 | Invalid closed shape, duplicate keys, counter tokens, bounds, or document/transition |
| 503 | Closed/disposed/unavailable schema authority |
| 500 | Sanitized storage/corruption failure |

Focused verification includes the shared portable document corpus, real Rust
router producer responses decoded by TypeScript, method/path consistency, raw
JSON differential cases, exact replay, role changes, closed production admission,
transaction rollback, concurrent history snapshot stability, 9-to-10 cursor
width, exact reply limits, chunked transport overflow, and late-operation fencing.
For the producer/decoder test, set `NATIVE_PROJECT_SCHEMA_RPC_FIXTURE` to the same
temporary output path for the Rust `project_schema_rpc_producer` test and the
TypeScript `native-project-schema-contract.test.mjs` run. Without that explicit
path the cross-process fixture check is reported as skipped, not as live evidence.
