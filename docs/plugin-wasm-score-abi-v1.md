# External WASM score ABI v1

The external V2 ToolSet factory uses `memstack.wasm.score-json-utf8.v1`.
This is distinct from the legacy `WasmtimeToolFactory` inline-WAT contract.
The Rust signed archive verifier admits bytes and ownership metadata only;
it does not compile a guest, register tools, or grant execution permission.

The v1 tool input schema is an object with exactly one `input` string, at most
65,536 Unicode code points. The host serializes the entire object as compact
JSON, with no whitespace outside strings and no unnecessary ASCII escaping
of Unicode characters, then encodes UTF-8. The guest receives the number of
bytes of that JSON document as an `i32` argument to its exported
`score(i32) -> i32` function. Length conversion must be checked, never truncated.

Examples: `{"input":""}` supplies 12; `{"input":"中"}` supplies 15.
Quotes, backslashes, and control characters count after JSON escaping.
The guest does not receive string contents or access to host memory.
Neither the character count of `text` nor a renderer-provided `len` field is
an implementation of this ABI. The existing Python V2 factory implements
the compact-JSON UTF-8 lowering. The optional native Rust `external-wasm-v2`
factory implements the same lowering with Unicode/escaping regression tests.

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

This ABI document does not enable Local marketplace installation or execution.
The signed archive verifier and optional V2 runtime factory have library tests.
Local governance persistence and ToolHost integration still need to be completed
and tested together through the native client.
