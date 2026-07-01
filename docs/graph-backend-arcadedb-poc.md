# ArcadeDB Graph Backend — POC + HA Runbook

## Status
- **Code**: complete. `ArcadeDBGraphStore` implemented, wired into `GraphBackendFactory`
  (`ENGINE_ARCADEDB`), unit-tested (7 tests), and covered by live-cluster POC tests
  (`src/tests/integration/graph/test_arcadedb_poc.py`).
- **Live validation**: PASSED against a single-node ArcadeDB container
  (`arcadedata/arcadedb:latest`, v26.7.x). All 5 POC tests green.
- **HA rehearsal**: three-node compose and skippable integration harness are present.
  The HA test only runs when `ARCADEDB_HA_ENABLE_FAILOVER=1` is set so CI stays
  green without local Docker state.

## HA source-of-truth
- ArcadeDB HA is Raft-based. The official HA guide requires
  `arcadedb.ha.enabled=true`, a peer list in `arcadedb.ha.serverList`, and unique
  `arcadedb.server.name` values per server. Raft uses port `2434` by default, and
  the HTTP port in each peer entry is used for forwarding writes to the leader.
- The runbook uses `arcadedb.server.defaultDatabases=memstack[root|arcadepw]` so
  every node declaratively creates the same database at boot.

References:
- https://docs.arcadedb.com/arcadedb/how-to/operations/ha.html
- https://docs.arcadedb.com/arcadedb/concepts/high-availability.html
- https://docs.arcadedb.com/arcadedb/concepts/databases.html

## How to reproduce the live POC
```bash
# 1. Start the ArcadeDB dev container (Bolt on 7688, HTTP on 2480).
docker compose -f docker-compose.arcadedb.yml up -d
#    Wait for healthcheck == healthy (~10s).

# 2. Run the POC tests:
ARCADEDB_URI=bolt://localhost:7688 ARCADEDB_PASSWORD=arcadepw \
PYTHONPATH=. uv run pytest src/tests/integration/graph/test_arcadedb_poc.py -v
# => 5 passed

# 3. Tear down:
docker compose -f docker-compose.arcadedb.yml down -v
```

## How to run the three-node HA rehearsal
```bash
# 1. Start the local HA cluster.
docker compose -f docker-compose.arcadedb-ha.yml up -d

# 2. Wait for the HTTP endpoints to become reachable:
#    node1 http://localhost:2481
#    node2 http://localhost:2482
#    node3 http://localhost:2483

# 3. Run the failover test. The flag is intentional: without it the suite skips.
ARCADEDB_HA_ENABLE_FAILOVER=1 \
ARCADEDB_HA_URI_1=bolt://localhost:7689 \
ARCADEDB_HA_URI_2=bolt://localhost:7690 \
ARCADEDB_HA_URI_3=bolt://localhost:7691 \
ARCADEDB_HA_HTTP_1=http://localhost:2481 \
ARCADEDB_HA_HTTP_2=http://localhost:2482 \
ARCADEDB_HA_HTTP_3=http://localhost:2483 \
PYTHONPATH=. uv run pytest src/tests/integration/graph/test_arcadedb_ha.py -v

# 4. Tear down all nodes and volumes after the rehearsal.
docker compose -f docker-compose.arcadedb-ha.yml down -v
```

The HA test writes a canary episode/entity/edge through node1, stops node1,
waits up to 30 seconds for node2 to pass `health_probe`, writes another canary
entity through node2, restarts node1, and checks the canary count remains visible
after recovery. It also calls `vector_search` and `fulltext_search` to verify both
methods keep returning list-shaped results during the failover rehearsal.

## Architecture decision: dual-transport (Bolt + HTTP SQL)

**Initial assumption** (pre-POC): ArcadeDB is Bolt-compatible, so subclass
`NativeGraphAdapter` and override only `vector_search` / `fulltext_search` with
Cypher. **This assumption was wrong.** Live testing against v26.7.x revealed that
ArcadeDB splits its surface across TWO languages:

| Capability | Transport | Language | Works? |
|---|---|---|---|
| Node/edge CRUD (`MERGE`/`SET`/`MATCH`/`DELETE`) | Bolt (7687) | OpenCypher | YES — with bound `$params`, indistinguishable from Neo4j |
| Schema DDL (`CREATE VERTEX/EDGE/PROPERTY TYPE`, `CREATE INDEX`) | HTTP (2480) | SQL | YES — but **Cypher rejects DDL** (`Syntax error ... mismatched input 'TYPE'`) |
| Vector index + similarity search | HTTP (2480) | SQL | YES — `LSM_VECTOR` index + `vectorNeighbors()` function |
| Fulltext search | HTTP (2480) | SQL | YES — `FULL_TEXT` index + `SEARCH_INDEX()` function |

`ArcadeDBGraphStore` therefore subclasses `NativeGraphAdapter` (reusing ALL Cypher
CRUD primitives over Bolt) and overrides three primitives to issue **SQL over HTTP**:

| Override | ArcadeDB SQL (over HTTP) |
|---|---|
| `initialize_schema` | `CREATE VERTEX/EDGE TYPE ...`, `CREATE PROPERTY ... ARRAY_OF_FLOATS`, `CREATE INDEX ... LSM_VECTOR METADATA {dimensions, similarity:"COSINE"}` |
| `vector_search` | `SELECT expand(vectorNeighbors('Entity[name_embedding]', [v1,v2,...], k))` |
| `fulltext_search` | `SELECT expand(SEARCH_INDEX('entity_name_summary', 'text'))` (+ lazy `FULL_TEXT` index create) |

The HTTP base URL, database name, and credentials are derived from the Bolt
client's URI/database/user/password so the two transports always agree.

## Key gotchas discovered (all resolved)

1. **Plugin must be explicitly enabled.** The Neo4j-Bolt plugin is bundled but
   NOT auto-loaded; without `-Darcadedb.server.plugins=Neo4j-Bolt:com.arcadedb.bolt.BoltProtocolPlugin`
   only HTTP listens (port 7687 never opens). See `docker-compose.arcadedb.yml`.
2. **Root password >= 8 chars.** ArcadeDB rejects shorter passwords at startup
   (`ServerSecurityException: User password too short`) and exits. Use `arcadepw`.
3. **No `curl` in the image.** Healthcheck must use `wget` against `/` (200).
4. **Database must pre-exist.** ArcadeDB does NOT auto-create databases on Bolt
   connect. The test fixture auto-creates `memstack` via `POST /api/v1/server`
   (`{"command":"create database memstack"}`); the client connects with
   `database="memstack"`.
5. **HTTP `/command` drops bound parameters.** Named (`:x`) and positional (`?`)
   SQL parameters are silently ignored on the HTTP command endpoint in this build.
   Dynamic values are serialized as **inline SQL literals**: vectors via
   `_sql_vec_literal` (float-only, injection-safe), text via `_sql_str_literal`
   (single-quote-doubled, newlines/backticks rejected).
6. **Vector property type is `ARRAY_OF_FLOATS`** (not `BINARY`) for the default
   FLOAT32 encoding; index type is `LSM_VECTOR` (not Neo4j's `VECTOR_INDEX`).
7. **Fulltext index type is `FULL_TEXT`** (not `FULLTEXT` / `LSM_FULLTEXT`).
8. **Cosine rejects zero vectors.** `vector_search` probes must use a non-zero
   vector (`Query vector cannot be a zero vector when using COSINE similarity`).
9. **`SEARCH_INDEX` takes the index NAME**, not `'Type[prop]'`.

## POC verification checklist (results)

| # | Check | Result |
|---|---|---|
| 1 | Bolt connectivity via `neo4j` async driver | PASS — `health_probe` returns True |
| 2 | OpenCypher CRUD (MERGE/SET/MATCH/DELETE with params) | PASS — round-trip verified |
| 3 | `vector_search` result shape (`GraphSearchHit`) | PASS — `vectorNeighbors` returns `{record, distance}` |
| 4 | `fulltext_search` result shape (`GraphSearchHit`) | PASS — `SEARCH_INDEX` returns matched records |
| 5 | `initialize_schema` idempotency | PASS — safe to call twice |
| 6 | HA failover (3-node leader kill) | SKIPPABLE LIVE — `docker-compose.arcadedb-ha.yml` + `test_arcadedb_ha.py` |

## How to register a per-project ArcadeDB backend
1. Insert a `graph_stores` row with `engine_type='arcadedb'` and `connection_config`:
   ```json
   {
     "uri": "bolt://arcadedb-host:7687",
     "user": "root",
     "password": "<>=8 chars>",
     "database": "memstack",
     "http_base_url": "http://arcadedb-host:2480"  // optional; derived from uri if omitted
   }
   ```
2. Set `projects.graph_store_id` to that store's id for the canary project.
3. The `GraphBackendRegistry` + `GraphBackendFactory` resolve it at request time;
   `build_arcadedb_backend` constructs the `ArcadeDBGraphStore` (Bolt client +
   HTTP SQL endpoint derived from the same config).

## Files
| File | Role |
|---|---|
| `docker-compose.arcadedb.yml` | Single-node dev container (Bolt 7688, HTTP 2480) |
| `docker-compose.arcadedb-ha.yml` | Three-node local HA cluster (Bolt 7689-7691, HTTP 2481-2483, Raft 24341-24343) |
| `src/infrastructure/graph/stores/arcadedb_graph_store.py` | Adapter: Bolt CRUD (inherited) + HTTP SQL overrides |
| `src/infrastructure/graph/backend_factory.py` | `build_arcadedb_backend` builder |
| `src/tests/integration/graph/test_arcadedb_poc.py` | 5 live-cluster POC tests (auto-skip if unreachable) |
| `src/tests/integration/graph/test_arcadedb_ha.py` | Failover rehearsal test (auto-skip unless explicitly enabled) |
| `src/tests/unit/infrastructure/graph/test_arcadedb_graph_store.py` | 7 unit tests (HTTP mocked) |

If HA failover fails on a real 3-node cluster, fall back to the Apache AGE
(Postgres) spike without touching the registry/factory design.
