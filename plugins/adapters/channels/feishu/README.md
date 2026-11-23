# Feishu channel adapter

This independently installable package formats the progress prefix of existing Feishu `task_start` and `task_complete` cards. The channel host adds the original task text and sends the card to the conversation's bound chat. The Wasm guest receives the event kind, status, zero-based position and total count. The full distribution ships the same guest for channels using the default format.

## Channel protocol

The full distribution loads the Python implementation from `backend/`. Start with `backend/adapter.py` for the connection lifecycle, `backend/webhook.py` for callbacks, and `backend/media.py` for media operations. A deployment can build the Python wheel from this directory with `uv build --wheel` and install it alongside MemStack. The signed project release currently replaces the task timeline renderer.

## Publish a release

Build with the Rust `wasm32-unknown-unknown` target. Update the version in `Cargo.toml` and `package.json` together for a new release. From the package directory, run the following commands with your own Ed25519 PKCS#8 publisher key.

```sh
cargo build --release --locked --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/memstack_feishu_timeline.wasm timeline.wasm
uv run --with ../../../../sdk/memstack-plugin-sdk memstack-plugin-pack package.json \
  --key "$SIGNING_KEY" --out feishu-timeline.mspkg
```

## Use the renderer in a channel

Configure the publisher's public key in `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES` on the API and the process forwarding channel events. A project administrator installs the archive, approves `tools.execute` and enables the release in the project. Update that project's Feishu channel via `PUT /api/v1/channels/configs/{config_id}` with `{"extra_settings":{"task_timeline_package":"memstack-feishu-timeline"}}`. Set this field to `null` to restore the distribution's default renderer.

The bridge resolves the package against the stored tenant, project, conversation and channel binding. Replacement packages implement the same `render_timeline` input and output and run as compute-only Wasm. Upgrades and rollbacks affect the next event for that channel. A disabled or unavailable selected renderer leaves the task text visible. Ordinary channel credentials and interactive HITL actions stay with the existing adapter.
