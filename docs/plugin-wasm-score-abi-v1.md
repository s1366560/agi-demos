# External WebAssembly tool ABIs

A signed module selects one export in its entrypoint. The Python and Rust V2 tool factories support the two ABIs below. The host checks the export signature against the verified archive before exposing a tool.

## Structured invoke

Export `memory` and `invoke(i32) -> i32`. The host serializes the operation's object as compact UTF-8 JSON and writes it at byte offset zero. The argument gives the input byte length, up to 65,536. The guest writes one UTF-8 JSON object at byte offset 65,536 and returns its byte length. The active quota can reduce the 65,536-byte result limit. A negative size, inaccessible memory, a malformed document or a result exceeding the limit fails the operation. Guests must reserve both buffers when laying out the stack and static data. Each invocation starts with a fresh store.

The project installer validates input and output against the schemas declared by the signed contribution. Packagers can build a device guest with the official knowledge retrieval example or a cloud guest with the Billing example.

## Score

`memstack.wasm.score-json-utf8.v1` accepts an object with one `input` string of at most 65,536 Unicode code points. The host serializes it as compact JSON without unnecessary ASCII escaping. The guest receives the UTF-8 byte count in `score(i32) -> i32` and returns a score. For example, `{"input":""}` supplies 12 and `{"input":"中"}` supplies 15. This entrypoint receives only the count. Quotes, backslashes and control characters count after JSON escaping.

## Runtime binding

The Rust factory consumes only `VerifiedWasmArtifactV2` and requires a signed
module declaring exactly `service:wasm-tool-set@1.0.0` as its provided service,
with no service requirements or event contracts. Its generated ToolSet is empty
for callers without an explicit operation authority and real generation lease.
This is a native Rust service contract. The Python factory instead contributes
to the Python builtin `service:tool-set-catalog`; a package supporting both
planes must declare separate modules with the correct per-target contracts.
The loader retains all manifests and uses a generation-local catalog overlay,
never changing or replacing the generated builtin catalog.

Before activation, the factory must validate the actual WASM bytes, the exact
export type, absence of imports/WASI, and supported module/manifest contract.
Compilation and invocation must run outside the async runtime event loop.
Every invocation requires fresh fuel, memory and wall-clock limits, bounded
output, a live generation lease, and current package/scope permission checks.
The immutable archive reference supplies bundle id, version, digest and source;
module/plugin identity comes from that same verified archive. Package and
plugin names may differ. Neither module config nor renderer input may supply
replacement attribution or verification evidence.

Archive signatures cover the v2 bundle digest, whose canonical domain form
includes absent Scope, Quota, artifact signature/provenance, and service
contribution fields as explicit null values. Detached
Ed25519 signatures are verified over the ASCII `sha256:...` digest string.
The signed provenance field is a reference; verifying its inclusion does not
assert that a referenced remote attestation has separately been evaluated.

The desktop device package settings use the current cloud identity, a device-bound approval and the Sidecar's verified archive loader. The renderer receives release metadata and operation-scoped results. See [the device package example](../plugins/business/knowledge/workers/device_search/README.md).
