# MemStack CLI

`memstack` is the command-line client in `sdk/memstack_cli`. It currently covers
authentication, project/conversation listing, persisted event inspection, and artifact
download.

Last checked against code: 2026-06-23.

## Install

```bash
# From this repository
uv pip install -e sdk/memstack_cli

# Once published
uv tool install memstack-cli
```

Verify:

```bash
memstack --version
memstack --help
```

## Authentication

API key lookup order:

1. `--api-key ms_sk_...`
2. `MEMSTACK_API_KEY`
3. `~/.memstack/credentials`

Interactive login uses the device-code API:

```bash
memstack login
memstack logout
```

`memstack login` calls `/auth/device/code`, opens the web UI `/device` approval page, polls
`/auth/device/token`, then stores the issued API key in `~/.memstack/credentials`.

## Commands

All commands accept global `--json` for machine-readable output.

```bash
memstack whoami
memstack projects
memstack conversations --project <project_id> --limit 20
memstack logs <conversation_id> [--limit N] [--from-sequence N] [--type event_type]
memstack artifacts list --project <project_id> [--category image]
memstack artifacts pull <artifact_id> [--output ./file.zip]
```

## Current Chat Status

The CLI still contains a legacy `memstack chat` command that targets `POST /agent/chat` and
optional SSE streaming. The current backend route set does **not** register
`/api/v1/agent/chat`; live chat is WebSocket-based at:

```text
WS /api/v1/agent/ws
```

Use the web console or a WebSocket client for live agent chat until the CLI chat command is
migrated. Do not use the legacy CLI chat examples as the current integration contract.

## Logs

```bash
memstack logs <conversation_id>
memstack logs <conversation_id> --limit 1000
memstack logs <conversation_id> --type tool_call
memstack --json logs <conversation_id>
```

The logs command reads persisted execution events from:

```text
GET /api/v1/agent/conversations/{conversation_id}/events
```

This is useful for triaging a stuck or failed run without opening the web UI.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MEMSTACK_API_URL` | `http://localhost:8000` | Backend API base URL |
| `MEMSTACK_API_KEY` | unset | API key fallback |

## Scripting Examples

```bash
# All project IDs
memstack --json projects | jq -r '.[].id'

# Conversation event dump
memstack --json logs "$CONVERSATION_ID" --limit 500 \
  | jq -r '.events[] | [.type, .timestamp] | @tsv'

# Pull every image artifact to ./out/
memstack --json artifacts list --project "$PROJECT_ID" --category image \
  | jq -r '.[].id' \
  | while read id; do
      memstack artifacts pull "$id" --output "./out/$id"
    done
```

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Runtime, network, or HTTP error |
| 2 | Bad input or missing authentication |

## Implementation Notes

- No daemon: each command is a one-shot HTTP call.
- Shared HTTP helper: `sdk/memstack_cli/memstack_cli/client.py`.
- Auth resolution: `sdk/memstack_cli/memstack_cli/auth.py`.
- Commands: `sdk/memstack_cli/memstack_cli/commands/*.py`.
- Chat migration target: replace legacy REST/SSE with the WebSocket protocol described in
  [api-reference.md](api-reference.md).
