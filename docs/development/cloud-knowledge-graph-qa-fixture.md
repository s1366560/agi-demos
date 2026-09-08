# Isolated Cloud graph provenance sample

This sample verifies graph transport, direction, UUID-based source lookup and UI navigation.
It is declared QA data saved through the production `Neo4jClient` public persistence methods.
It does not prove LLM extraction, embedding, memory processing or background execution.

The QA API admits only these production graph routes:

- `GET /api/v1/graph/memory/graph`
- `POST /api/v1/graph/memory/graph/subgraph`

Both retain their production authentication, tenant/project access checks and graph runtime.
No graph mutation route is exposed. Existing synchronization records and the compiled profile
are unchanged by this addition.

## Seed

Use the existing QA metadata and an existing, readable QA memory. From the repository root:

```bash
.venv/bin/python -m scripts.qa_cloud_knowledge_graph_fixture seed \
  --metadata /path/to/qa-metadata.json \
  --tenant-id "$QA_TENANT_ID" \
  --project-id "$QA_PROJECT_ID" \
  --memory-id "$QA_MEMORY_ID"
```

The command validates the fixed QA database, generated schema name and exact loopback Neo4j
address (`bolt://127.0.0.1:17687`). It confirms `current_schema()` and resolves the project and
memory through the production SQL repositories before opening the graph connection. It reads
PostgreSQL without changing memories, revisions, enrollment, cursors or tasks.

The fixture UUID namespace includes the QA schema, tenant, project, memory and fixture version.
Repeated seeding of the same scope reuses the same persisted UUIDs. Before any graph write, all
existing fixture nodes must match their tenant, project and `qa_fixture_id`. The public writer
also rejects a client targeting the shared graph address or a different graph database.

The JSON result lists the fixture identity, node UUIDs, directed endpoints and missing-source
UUID. It contains no authentication token or password. The graph element IDs returned by the
API are separate Neo4j element IDs; use the listed UUIDs only for source lookup.

## Expected sample

Five nodes and seven edges are created:

| Data | Expected behavior |
| --- | --- |
| `QA Graph Captured Source` | Captured content begins `QA_GRAPH_CAPTURE_V1`; it points to the supplied existing memory. |
| `QA Graph Unlinked Source` | Captured content begins `QA_GRAPH_UNLINKED_V1`; no associated memory link exists. |
| Two `QA Graph Duplicate Name` entities | Distinct UUIDs and summaries A/B; navigation must use identity. |
| `QA Graph Membership` community | Membership alone does not imply a source reference. |
| Three `MENTIONS` edges | Linked source mentions A/B; unlinked source mentions B. |
| `QA_SUPPORTS`: A to B | Has `QA_GRAPH_FORWARD_V1` fact and linked/missing source UUIDs. |
| `QA_REPLIES_TO`: B to A | Has `QA_GRAPH_REVERSE_V1` fact and the unlinked source UUID. |
| `QA_SELF`: A to A | Self relationship appears once in adjacency. |
| `BELONGS_TO`: A to community | Has no episode evidence property. |

Request each source through the scoped subgraph route with
`node_uuids: [source_uuid]`, `include_neighbors: false`, `limit: 1`, and the explicit tenant/project.
The missing-source UUID must yield an empty source result. A source lookup in another project
must not return the sample. Neighbor expansion around entity B must preserve A-to-B and B-to-A
directions despite beginning the traversal at B.

In Web and native Desktop, choose a relationship, follow each directed endpoint, read the source,
and then open/read the current memory separately. Updating the current memory through its normal
UI must not alter the captured fixture source. A missing or inaccessible source must clear prior
source content and the old current-memory link. Graph lists remain explicitly limited views.

## Cleanup

Run before removing the QA project/schema. The original memory may already be deleted:

```bash
.venv/bin/python -m scripts.qa_cloud_knowledge_graph_fixture cleanup \
  --metadata /path/to/qa-metadata.json \
  --tenant-id "$QA_TENANT_ID" \
  --project-id "$QA_PROJECT_ID" \
  --memory-id "$QA_MEMORY_ID"
```

Cleanup validates the project and every remaining node's ownership, then calls the production
client's `delete_node` only for this fixture's five UUIDs. It does not delete a project graph,
change SQL data, remove a schema or reset synchronization data.
