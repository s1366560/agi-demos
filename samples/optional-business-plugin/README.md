# Optional business sample

This directory is source for a signed package. It is not a host builtin and it is not registered in the generated module catalog.

`tool.wat` exports `invoke` and writes a JSON object at byte offset 65536. `ui.json` is the structured slot document. The host test compiles the WAT, checks the UI digest, and runs the package through `SignedOptionalBusinessRuntimeV2`.

The SDK at `sdk/memstack-plugin-sdk` is the contract. It is not published.
