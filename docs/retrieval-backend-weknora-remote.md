# WeKnora Remote Retrieval Backend

## Scope
`weknora_remote` is an optional remote retrieval adapter. It keeps WeKnora out of
the MemStack runtime dependency graph: MemStack talks to an already running
WeKnora API over HTTP and normalizes search rows into `RetrievalSearchResult`.

This adapter does not replace the MemStack graph contract. Graph writes and graph
queries still use the selected `GraphStorePort` backend.

## Connection config
`base_url` must be the WeKnora API root, not the host root:

```json
{
  "base_url": "http://weknora-host:8080/api/v1",
  "api_key": "sk-...",
  "knowledge_base_id": "kb-id"
}
```

Supported fields:

| Field | Required | Notes |
|---|---:|---|
| `base_url` | yes | API root such as `http://host:8080/api/v1`. |
| `api_key` | yes | Sent as `X-API-Key`. Masked as `***` in API/UI responses. |
| `knowledge_base_id` | one of KB fields | Single KB target. |
| `knowledge_base_ids` | one of KB fields | Multi-KB target when WeKnora deployment supports it. |
| `search_path` | no | Defaults to `/knowledge-search`. |
| `health_path` | no | Defaults to `/health`. |
| `index_path` | no | Reserved for future remote indexing. |
| `delete_path` | no | Reserved for future remote delete-by-source. |

Store management follows the same envelope shape as WeKnora vector-store APIs:
`/retrieval-stores/types`, `/retrieval-stores/test`, CRUD, and
`/{store_id}/test`. MemStack allows editing connection config for user stores;
WeKnora's documented VectorStore service currently treats name as the only
regular mutable field and exposes connection-config updates as a separate service
method.

## Live integration test
The live suite is opt-in and skipped unless all required env vars exist:

```bash
WEKNORA_BASE_URL=http://localhost:8080/api/v1 \
WEKNORA_API_KEY=sk-xxxxx \
WEKNORA_KB_ID=your-kb-id \
PYTHONPATH=. uv run pytest src/tests/integration/retrieval/test_weknora_remote_live.py -v
```

The test checks:

- `health_probe` returns a boolean without leaking credentials.
- `detect_version` accepts both top-level and nested version payloads.
- `hybrid_search` accepts WeKnora `knowledge-search` responses shaped as
  `{ "success": true, "data": [...] }`.
- `success:false` is treated as an explicit adapter error, not as an empty result
  set.
- Normalized results never include the configured API key.

## KB preparation
Prepare a small WeKnora knowledge base before running the live test:

1. Start WeKnora with a supported vector store and a valid API key.
2. Create or choose one knowledge base.
3. Upload at least one short text document that contains a stable term such as
   `memstack`.
4. Wait for WeKnora indexing to finish.
5. Export the KB id as `WEKNORA_KB_ID`.

The live test uses a low-risk query and accepts empty results if the KB is empty,
but a seeded KB is required to prove score/text normalization with real rows.

## Response normalization
`weknora_remote.hybrid_search` accepts:

- A raw list of row objects.
- `{ "success": true, "data": [ ... ] }`.
- `{ "success": true, "data": { "results": [ ... ] } }`.
- Equivalent `items` or `chunks` containers under `data`.

When `success` is explicitly `false`, the adapter raises `WeknoraRemoteError`
using `error`, `message`, or `msg` from the response payload.

Row fields are normalized conservatively:

| WeKnora-like field | MemStack field |
|---|---|
| `id`, `chunk_id`, `document_id` | `chunk_id` fallback chain |
| `text`, `content`, `chunk_text` | `text` |
| `score`, `similarity`, `distance` | `score` |
| `metadata`, `document`, `source`, `knowledge_base_id` | `metadata` |

## Troubleshooting
- 401/403 on health or search: verify `WEKNORA_API_KEY` and that the deployment
  expects `X-API-Key`.
- 404 on search: ensure `base_url` includes `/api/v1`; otherwise set
  `search_path` explicitly.
- Empty live search: confirm the KB contains indexed chunks and the query term is
  present in the uploaded content.
- Secret visible in UI/API response: treat as a bug. Store responses must use the
  masked `connection_config`; never return raw `api_key`, `password`, `token`, or
  `authorization` values.
- `success:false` from WeKnora: the adapter now raises a clear error so operators
  see the upstream failure instead of a silent zero-result search.
