# deepseek chat adapter

The project administrator grants `tools.execute` and `model.chat.adapt.deepseek`. A host selects this release for its provider, pins the release on the run and rechecks both package and tenant provider grants before each chunk. OpenAI and DeepSeek releases can be enabled and rolled back independently. A second adapter for an already-covered transport conflicts at enable time.

Change the stream policy in [src/lib.rs](src/lib.rs). With the Rust Wasm target installed, build and sign this directory using the publisher's key.

```sh
cargo build --locked --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/memstack_deepseek_chat.wasm adapter.wasm
memstack-plugin-pack package.json --key "$PUBLISHER_KEY_FILE" --out deepseek.mspkg
```

The guest sees the provider identifier, requested budget and tool presence. Credentials, transport and response text remain with the host. See the [local SSE and project authorization tests](../../../../src/tests/integration/test_project_chat_stream_adapter.py).
