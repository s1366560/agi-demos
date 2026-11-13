# MCP protocol 2026-07-28

The current stable Model Context Protocol revision is `2026-07-28`.

- Specification: https://modelcontextprotocol.io/specification/2026-07-28/basic
- Versioning: https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning
- Release note: https://blog.modelcontextprotocol.io/posts/2026-07-28/

Stable SDKs that implement that revision, as published on 2026-11-13:

- Python `mcp` 2.3.0: https://pypi.org/project/mcp/2.3.0/
- TypeScript `@modelcontextprotocol/client` 2.4.0: https://www.npmjs.com/package/@modelcontextprotocol/client
- Rust `rmcp` 3.10.0: https://crates.io/crates/rmcp/3.10.0

`2026-12-15` is listed as not ready and is not used. The TypeScript v1 package
`@modelcontextprotocol/client` 2.4.0 is the current stable TypeScript client
package, but its published `LATEST_PROTOCOL_VERSION` is `2025-11-25` and its
`SUPPORTED_PROTOCOL_VERSIONS` stops there. Its request types also diverge from
the v1 types still used by `@mcp-ui/client`. The browser session therefore
stays on the latest v1 maintenance release, `@modelcontextprotocol/sdk`
1.32.2, which negotiates through `2025-11-25`. The Python and Rust paths in
this tree offer `2026-07-28` directly.

This tree offers `2026-07-28` and still accepts `2026-01-26`, `2025-11-25`,
`2025-06-18`, `2025-03-26`, and `2024-11-05`. Any other revision is rejected
with `unsupported_protocol_version`. The sandbox server also answers
`server/discover` with that list. Capabilities stay limited to the tools,
resources, and prompts the server already implements. Sampling, tasks,
elicitation, and other optional 2026 features are not declared.

The desktop sidecar speaks the protocol itself over stdio, Streamable HTTP,
legacy SSE, and WebSocket. It does not take a dependency on `rmcp`, because
that crate is not the transport used for the sandbox WebSocket. `rmcp` 3.10.0
is the stable Rust SDK for the same specification.

Internal plugin v2 route generations are unchanged. This upgrade does not
change the Ollama or LiteLLM streaming tool-call behavior.
