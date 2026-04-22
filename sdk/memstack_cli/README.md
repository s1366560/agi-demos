# memstack-cli

Command-line interface for MemStack. Send prompts, browse conversations,
fetch artifacts — all from a terminal or a script.

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
memstack chat <project_id> "hello" --stream
memstack artifacts list --conversation <id>
memstack artifacts pull <artifact_id> --output ./out.zip
```

See [docs/CLI.md](../../docs/CLI.md) for the full reference.
