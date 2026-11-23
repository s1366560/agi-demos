# Cohere project search reranking

This compute-only Wasm package adapts a project's advanced graph search to the native Cohere rerank protocol. It selects bounded request options from the requested result count, then maps Cohere's numeric positions and relevance scores back into ranked candidates. Both operations use the same signed release. The platform's LiteLLM transport owns the model, endpoint, credentials, query and document text.

## Build and sign

From this package directory, build with the Rust `wasm32-unknown-unknown` target, then sign with the publisher's Ed25519 key. For a new release, update the versions in `Cargo.toml` and `package.json`.

```sh
cargo build --locked --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/memstack_cohere_rerank.wasm adapter.wasm
uv run --with ../../../../sdk/memstack-plugin-sdk memstack-plugin-pack package.json \
  --key "$SIGNING_KEY" --out cohere-rerank.mspkg
```

## Deploy to a project

1. Configure the publisher's public key in `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES` on the API. In provider administration, assign an active, enabled Cohere provider with a permitted rerank model to the target tenant's `rerank` role. Its persisted authentication and endpoint are used for the actual HTTP request.
2. As a project administrator, install and enable the archive with `tools.execute`. Update the project's `graph_config` through `PUT /api/v1/projects/{project_id}`, preserving its other graph settings and setting `cohere_rerank_package` to `memstack-cohere-rerank`.
3. Submit an authorized request to `POST /api/v1/search-enhanced/advanced` with `project_id`, `query` and `limit`. Two or more candidates trigger reranking. Empty and single-candidate searches need no provider call. On package or transport failure the API reports HTTP 503. Removing the selection restores normal search ordering.

The administrator's project setting selects the package. Model requests use the current tenant's explicit provider assignment. A second tenant requires its own assignment. The adapter's output schema accepts only `top_n` and `max_chunks_per_doc` on request construction. The host accepts at most the original result limit and 10 chunks per document. Returned positions must identify distinct candidates supplied by that provider response. This package covers non-streaming graph search reranking. Chat and embeddings use their existing provider paths.
