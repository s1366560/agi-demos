# memstack-cli

Command-line interface for MemStack. Browse projects and conversations, inspect persisted
events, and fetch artifacts from a terminal or script.

## Install

```bash
uv tool install memstack-cli
# or, during development from this repo:
uv pip install -e sdk/memstack_cli
```

## Quick start

```bash
memstack login                      # device-code OAuth
memstack whoami
memstack projects
memstack conversations --project <id>
memstack artifacts list --conversation <id>
memstack artifacts pull <artifact_id> --output ./out.zip
```

`memstack chat` still exists in the CLI code, but it targets the legacy REST/SSE chat route.
Current live agent chat is WebSocket-based; see [docs/CLI.md](../../docs/CLI.md) for the
current status.

See [docs/CLI.md](../../docs/CLI.md) for the full reference.
