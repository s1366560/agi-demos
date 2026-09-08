# Isolated Cloud knowledge synchronization QA API

This is an opt-in development entrypoint. It binds to `127.0.0.1`, uses only the
existing `memstack_qa_sync_20260907` PostgreSQL database, and allocates a new
`qa_cloud_sync_<random UUID>` schema. It never publishes into a shared ROOT ledger
or changes the product's default profile.

Run commands from the repository root. The repository `.env` supplies PostgreSQL
host credentials; the QA database name is fixed in code. `DATABASE_URL` supplied
only through the shell is deliberately not a substitute for repository settings.
The dedicated database must already contain the `public.vector` extension type.
An isolated Neo4j instance must be running at `bolt://127.0.0.1:17687` with
`NEO4J_AUTH=none`. The CLI requires that exact explicit QA address and never uses
the shared Neo4j configuration.
No connection uses `public` as a fallback in its search path.

## Initialize and start

Choose a new metadata filename. In zsh, read a temporary QA password without
printing it or writing it into shell history:

```sh
read -rs 'QA_CLOUD_SYNC_PASSWORD?Temporary QA password: '
export QA_CLOUD_SYNC_PASSWORD
uv run python -m scripts.qa_cloud_knowledge_sync_api init \
  --metadata /tmp/cloud-knowledge-qa-run.json \
  --email cloud-qa@example.test \
  --neo4j-uri bolt://127.0.0.1:17687
unset QA_CLOUD_SYNC_PASSWORD
uv run python -m scripts.qa_cloud_knowledge_sync_api serve \
  --metadata /tmp/cloud-knowledge-qa-run.json --port 18080
```

Initialization uses Alembic autogeneration for dependency tables, then applies the
real `a931fc278146` and `b353e93ff302` knowledge revisions. The historical empty
baseline cannot initialize these tables in a fresh schema. `AuthService.create_user`
creates a real user through SQL repositories; authentication is never overridden.
The metadata file contains only database/schema/profile identity, the isolated Neo4j URI, and creation time,
with mode `0600`. It contains no password, API key, connection URL or bearer token.

Connect the native Cloud connection form to `http://127.0.0.1:18080` using the
selected email and password. The local workspace remains active.

## Seed and exercise through production HTTP

1. Log in at `POST /api/v1/auth/token` using form fields `username` and `password`.
   Retain the returned bearer token privately. `GET /api/v1/auth/me` returns the
   actual `user_id` and `is_active` fields.
2. Create a tenant with `POST /api/v1/tenants/`, then create a project with
   `POST /api/v1/projects/` and its `tenant_id`. List/detail endpoints use the
   same authenticated membership checks as production.
3. Observe `GET /api/v1/projects/{project_id}/knowledge-sync/enrollment`. Send its
   full `generation` object as JSON in `X-Memstack-Knowledge-Sync-Generation` on
   `POST /enrollment`, with body `{"contract_version":"1.0.0","operation":"enroll"}`.
4. Create a memory with `POST /api/v1/memories/`, `Idempotency-Key` set to a new UUID,
   and `X-Memory-Expected-Revision: 0`. Update with
   `PATCH /api/v1/memories/{memory_id}`, a new idempotency key, and the current
   revision in both the header and JSON `version` field. List with
   `GET /api/v1/memories/?project_id=...`; read details with
   `GET /api/v1/memories/{memory_id}`. Detail graph context uses real Cypher
   queries against the isolated Neo4j instance.
5. Use the native client's explicit target selection, enrollment and association,
   then pull/push/conflict actions. All six synchronization endpoints retain their
   production generation, authorization, enrollment and revision checks.

The QA memory write guard rejects unenrolled projects before the legacy processing
path can run. Enrolled writes persist the production revision-safe `PENDING` task
record, but no worker is started. The QA task manager refuses dispatch and starts
no periodic cleanup. The graph adapter is the production `NativeGraphAdapter` and returns actual graph
query results. LLM generation and embedding dependencies explicitly reject calls;
this process does not validate Cloud extraction or indexing.

The exact generated `memstack-cloud-knowledge-sync-acceptance-v2` snapshot is
validated and applied to a process-local V2 host. Route selection narrows the
exposed HTTP surface without changing that snapshot. Profile metadata must still
match the generated template when restarting; rebuild a QA run after an intentional
profile/contract change. Merely restarting does not require a new schema.

## Restart and explicit cleanup

Stop the process, then run the same `serve` command. The schema, real user/API keys,
project enrollment, journal and memory revisions remain intact. There is no
implicit cleanup on shutdown. No worker or other API process uses this schema.

After stopping the service, read the exact schema name from this run's metadata
and pass it explicitly:

```sh
uv run python -m scripts.qa_cloud_knowledge_sync_api cleanup \
  --metadata /tmp/cloud-knowledge-qa-run.json \
  --confirm-schema qa_cloud_sync_REPLACE_WITH_THIS_RUN_UUID
```

Cleanup rejects any other database or schema name and drops only the explicitly
confirmed schema. Historical `sync_*` fixture schemas and `public` are not touched.
Keep or delete the nonsecret metadata file as an evidence record after cleanup.

## Automated verification

```sh
KNOWLEDGE_SYNC_POSTGRES_TESTS=1 uv run pytest \
  src/tests/integration/test_qa_cloud_knowledge_sync_api.py -q
```

The tests use a new schema and a temporary random password, exercise real login,
production tenant/project creation, enrollment, memory writes, and fresh-host
restart. They explicitly clean up only their own schema afterward.
