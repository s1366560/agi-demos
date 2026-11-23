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

Project administrators can install signed archives with explicit permissions, inspect running
releases, and roll back a package. Project members can discover the commands of a running
release and invoke a command by name.

```bash
memstack --json packages --tenant "$TENANT_ID" --project "$PROJECT_ID" inspect billing.zip
memstack packages --tenant "$TENANT_ID" --project "$PROJECT_ID" install --approve tools.execute --approve ui.slot billing.zip
memstack packages --tenant "$TENANT_ID" --project "$PROJECT_ID" list
memstack plugin memstack-billing quote-pro --tenant "$TENANT_ID" --project "$PROJECT_ID"
memstack packages --tenant "$TENANT_ID" --project "$PROJECT_ID" rollback memstack-billing
```

See [docs/CLI.md](../../docs/CLI.md) for the full reference.
