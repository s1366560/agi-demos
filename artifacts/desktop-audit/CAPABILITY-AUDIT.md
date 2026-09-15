# Desktop Sidecar Runtime Capability Audit

Date: 2026-09-10 (final one-pass run at 12:51 UTC)
Scope: local mode, real `agistack-desktop-sidecar` + real `memstack-workspace-core`, driven end-to-end over the HMAC control-pipe handshake, the authenticated HTTP API, and the agent WebSocket.
Result: **7/7 capabilities WORKS. No sidecar bugs found; no source changes were required.**

## Method

Spawn path (same as `agi-stack/apps/desktop/tests/real-sidecar-integration.test.mjs`):
`SidecarSupervisor` (compiled at `/tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js`)
spawns `agi-stack/target/debug/agistack-desktop-sidecar` with
`.cache/avernet-bcs/target/debug/memstack-workspace-core`, fresh temp `dataDirectory`/`workspaceRoot`,
stdin `initialize` handshake -> `ready` frame verified via HMAC-SHA256 proof.

Auth facts discovered (all verified at runtime):

- Every HTTP request needs BOTH the launch capability AND a user session:
  `x-agistack-launch: <apiToken>` + `Authorization: Bearer <session access_token>`.
  Session obtained via `POST /api/v1/auth/local-session` (body `{trusted_device:false}`) with the launch token.
- Agent WS subprotocols: `['memstack.launch', apiToken, 'memstack.auth', sessionToken]`
  (the launch token alone as `memstack.auth` fails `require_user_session`).
- Default seeded context: tenant `northstar`, project `desktop-client`, role `owner`.

LLM: no real provider key was available (`GEMINI_API_KEY`/`OPENAI_API_KEY`/`DASHSCOPE_API_KEY`/
`DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY` unset; `KIMI_API_KEY` set but unused to keep the audit
hermetic and offline). A loopback mock OpenAI-compatible server
(`artifacts/desktop-audit/lib/mock-llm.mjs`) serves `POST /v1/chat/completions` (JSON + SSE),
scripted per stage. It was registered in the sidecar as an `openai_compatible` provider with
`auth_method: "none"`, `is_active: true`, loopback `base_url` (loopback HTTP is explicitly allowed
by `normalized_runtime_provider_base_url`), then bound via
`PUT /api/v1/llm-providers/:id/runtime-selection` (`expected_revision` required).

Important protocol note: the sidecar's ReAct engine does not use OpenAI-native `tool_calls`.
`LlmPort::decide` asks the model for a structured JSON action
(`{"kind":"finish","answer":...}` / `{"kind":"call_tool","tool":...,"input_json":{...}}`)
over plain chat completions (see `crates/adapters-http-llm/src/openai.rs`, `AgentActionWire`).
The mock speaks exactly that protocol.

## Verdict table

| # | Capability | Verdict | Evidence (final run) |
|---|------------|---------|----------------------|
| 1 | Workspace | WORKS | 4 tenants / 3 projects listed; workspace `2376be53-...` created via sidecar -> workspace-core bridge and present on re-list (persistence); task-session `d3e5a031-...` created via `POST .../task-sessions` |
| 2 | Simple conversation | WORKS | `ack -> user_message -> assistant_message -> complete(success)`; history GET returns both user and assistant messages; 1 LLM request |
| 3 | LLM provider | WORKS | provider created, runtime-selected (`runtimeSelected: true`, state `configuration_valid`), health-check HTTP 200; used by all conversation stages |
| 4 | Skills | WORKS | skill created via parity route (MutationEnvelope contract v2), listed; forced via `forced_skill_name`; streamed `skill_matched -> skill_execution_start -> skill_execution_complete` |
| 5 | Tool calls | WORKS | mock returned `call_tool` for the local `list` tool; streamed `act -> observe` pair; observation payload contains the real directory listing of the workspace root (`.agistack` entry) |
| 6 | Agent & subagent | WORKS | agent + subagent created via parity routes and listed; Plan-mode run submitted plan; `approve-and-start` entered Build mode; parent called the `subagent` tool; streamed `subagent_routed -> subagent_started -> subagent_session_update -> subagent_completed -> observe -> complete` |
| 7 | Plugins | WORKS (local surface) / UNAVAILABLE-BY-DESIGN (cloud surface) | control-pipe `platform_plugin_renderer_distribution_current_v2` -> `{source:"local", schema_version:2}`; `platform_plugin_renderer_delivery_current_v2` returns the local renderer snapshot; v1 HTTP APIs correctly return 410 `plugin_protocol_v1_retired`; `GET /api/v1/plugin-marketplace/packages` returns 503 `plugin_marketplace_v2_cloud_authority_unavailable` (requires a cloud trusted session — correct in local mode) |

No BROKEN-UNFIXED items. No FIXED items (no product code changed).

## Findings classified as audit-script setup issues (not sidecar bugs)

Each was diagnosed from the runtime error payload and resolved in the script:

1. 401 `local runtime launch capability required` — requests must carry both auth layers (see Method).
2. 422 on `POST .../task-sessions` — body must be `{idempotency_key, workspace:{kind:"existing",workspace_id}|{kind:"create",...}, conversation:{title,capability_mode}, initial_message:{content}}` (deny_unknown_fields).
3. 422 on provider `runtime-selection` / `health-check` — `expected_revision` is mandatory (optimistic concurrency).
4. `selected Agent, Skill, and Sub Agent have no shared tools` — a skill resource must declare `tools: [...]`; the run profile intersects agent/skill/subagent tool authorities.
5. `agent allowed_skills is required`, `agent allowed_mcp_servers is required` — agent definitions must declare all three allowlists.
6. Parent was offered only `["read","list","submit_plan"]` — the `subagent` delegation tool is attached only when `conversation.current_mode == Build` (`local_runtime/mod.rs:2301`). Plan->Build requires `POST /api/v1/agent/plans/approve-and-start` (with `permission_profile`); direct mode switching to Build is rejected by design ("build mode requires atomic plan approval and run authorization").
7. `agent can_spawn is required` — spawning agents need `can_spawn: true` plus `spawn_policy.allowed_subagents` (`subagent_agent_tool_host.rs:338-353`).

## Observations (design notes, not defects)

- Assistant replies stream at event granularity (`assistant_message` with full content), not
  token-level `text_start/delta/end`. The sidecar's local event vocabulary has no token-delta
  frames; the SSE path in `adapters-http-llm` (`stream_complete`) is not used by the local
  ReAct `decide` loop.
- Provider health-check reports catalog `availability: unavailable` against the mock because the
  mock does not implement `/models` discovery; the chat path itself is fully functional.
- `ensure_sandbox`/`start_desktop` return 501 "isolated local sandbox is not configured" — local
  mode uses the native Electron window (by design).

## Reproduction

```bash
cd artifacts/desktop-audit
node smoke.mjs        # handshake + session + tenants/projects sanity
node run-audit.mjs    # full 7-capability audit (one pass; ~10s)
node run-audit.mjs cap3_llm_provider cap6_agent_subagent   # single stages
```

Artifacts:

- `artifacts/desktop-audit/lib/harness.mjs` — spawn/handshake/session/HTTP/WS helpers
- `artifacts/desktop-audit/lib/mock-llm.mjs` — loopback OpenAI-compatible mock LLM
- `artifacts/desktop-audit/run-audit.mjs` — 7-stage audit orchestrator
- `artifacts/desktop-audit/logs/audit.log` — full WS event log of the final run
- `artifacts/desktop-audit/logs/results.json` — machine-readable verdict record (single final run)

Process hygiene: every spawned sidecar/workspace-core/mock process is stopped in `finally`
blocks; verified no audit-spawned processes remain (the two long-running
`/Applications/agi-stack Desktop.app/...` processes predate the audit and belong to the
installed app — untouched).
