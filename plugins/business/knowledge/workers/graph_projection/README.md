# Project graph projection

An enrolled project's episode workflow can use this package to convert extracted entities and edges into the knowledge sync journal's positional representation. The input contains entity IDs, names, types and relationship fields. The worker receives its input over private MCP stdio and has no database or network access.

From the repository root, build and push the OCI image, then provide its immutable digest to the [knowledge package builder](../../README.md).

```sh
docker build -t "$PROJECTION_IMAGE_TAG" plugins/business/knowledge/workers/graph_projection
docker push "$PROJECTION_IMAGE_TAG"
```

With the publisher trusted and the image registry allowed by the deployment, a project administrator installs and enables the signed archive. Approve `tools.execute` and `graph.projection.compute` for the selected tool, `ui.slot` for its Web and desktop pages, and `app.knowledge.memories.read` for its scoped persistent memory directory. Set `graph_config.sync_projection` to `{"plugin_id":"memstack-knowledge","tool":"project_graph"}` via the project's update endpoint, preserving its other graph configuration fields. Knowledge sync enrollment and the calling user's project execution rights are also required.

`POST /api/v1/memories/{memory_id}/reprocess` admits the exact source revision. The host pins the signed release digest and authorization epoch before graph extraction and persists a replayable snapshot before invoking the worker. Open jobs keep their release through package upgrades. A successful projection and its journal cursor commit in the same database transaction. The full API's recovery loop retries pending conversion using the saved snapshot. A withdrawn grant, superseded source or changed selection discards that job's snapshot. Fresh operations can use a rolled-back release. Projects without a selected, enrolled package retain their existing processing paths.

Task results report `projection_state`. `extracting` covers the native graph operation, `pending` means extraction completed and conversion can retry, `complete` means the journal accepted it, and `withdrawn` means its authority or source ended. If extraction loses its process before storing a snapshot, PostgreSQL releases the extraction guard and recovery marks the job `review`. Native extraction writes Neo4j across multiple transactions. Reconciliation in that state requires checking the original graph effects before a new extraction. The worker accepts up to 200 nodes and 500 edges, with a 120 KB serialized input envelope and the host's 64 KiB structured response limit.
