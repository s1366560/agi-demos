# MemStack CLI

`memstack` is the command-line interface for the MemStack platform. It
covers the end-user developer flow: authenticate, list projects, send
prompts, fetch artifacts.

## Install

```bash
# Once published
uv tool install memstack-cli

# From this repo (development)
uv pip install -e sdk/memstack_cli
```

Verify:

```bash
memstack --version
memstack --help
```

## Authentication

Three ways to supply an API key, in order of precedence (first hit wins):

1. `--api-key ms_sk_...` flag on any subcommand
2. `MEMSTACK_API_KEY` environment variable
3. `~/.memstack/credentials` (written by `memstack login`)

### Interactive login (device-code)

```bash
memstack login
```

The CLI prints a `user_code` (e.g. `AB23CDEF`) and a verification URL,
then opens your browser to the `/device` page on the MemStack web UI.
The code is pre-filled via `?user_code=...`, so you just click
**Approve** (sign in first if needed). The CLI receives a 30-day API
key and stores it at `~/.memstack/credentials` (0600).

Scripted hosts can pass `--api-key` or set `MEMSTACK_API_KEY` instead.

### Logout

```bash
memstack logout
```

Removes the credentials file.

## Commands

All commands accept a global `--json` flag that emits machine-readable
JSON to stdout instead of human-formatted text.

```bash
memstack whoami                     # current user + tenant
memstack projects                   # list projects in your tenant
memstack conversations --project <id>
memstack chat <project_id> "hello" [--conversation <id>] [--stream]
memstack artifacts list --project <id> [--category image]
memstack artifacts pull <artifact_id> [--output ./file.zip]
```

### Streaming chat

```bash
memstack chat <project_id> "summarize last meeting" --stream
```

`--stream` consumes the server-sent events from `/agent/chat`, printing
`[event_type] text` lines. Combine with `--json` to emit `{event, data}`
JSON per line — suitable for `jq` pipelines.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `MEMSTACK_API_URL` | `http://localhost:8000` | Base URL of the API |
| `MEMSTACK_API_KEY` | (unset) | Fallback API key |

## Scripting examples

```bash
# All project IDs
memstack --json projects | jq -r '.[].id'

# Tail a conversation's events
memstack chat "$P" "status?" --stream --json \
  | jq -r 'select(.event=="message") | .data'

# Pull every image artifact to ./out/
memstack --json artifacts list --project "$P" --category image \
  | jq -r '.[].id' \
  | while read id; do
      memstack artifacts pull "$id" --output "./out/$id"
    done
```

## Troubleshooting

- `error: no API key` — run `memstack login` or set `MEMSTACK_API_KEY`.
- Login times out — the approval window is 10 minutes. Re-run `memstack login`.
- `HTTP 401` on every call — the stored key expired; `memstack login` again.
- Need to hit a different server: `MEMSTACK_API_URL=https://... memstack whoami`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Runtime / network / HTTP error |
| 2 | Bad input (missing auth, missing arg) |

## Design

- **No daemon** — every command is a one-shot HTTP call. Lower ops
  surface; the CLI can run anywhere Python 3.12 runs.
- **Device-code flow** — lets CI and headless machines log in without
  storing a browser session. Scripts can still use `--api-key`.
- **Flag > env > file precedence** — matches mainstream CLI conventions
  (`kubectl`, `gh`, `aws`).

See `sdk/memstack_cli/` for the implementation. Each subcommand lives in
`memstack_cli/commands/*.py` and shares the same `client.request()` /
`auth.resolve_api_key()` helpers.
