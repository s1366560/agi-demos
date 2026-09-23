# Desktop Capability Audit — Pass 4 (workspace / conversation / skills / plugins / tool calls / agent / subagent)

Scope: full re-audit of the seven capability areas named in the 2026-09-18 goal, against the
current tree (post 2026-09-17 roadmap delivery). Five parallel audit passes cross-checked the
desktop renderer, the Electron main policies, the sidecar/workspace-core contracts, the FastAPI
backend, and the web reference. Every finding below was verified against both sides before fixing.

Baseline at audit start: frontend 4856 pass / Rust sidecar 926 pass / `build:electron` clean.
All suites re-run green after the fixes (frontend 4857 pass, backend targeted 120+21, web 10).

## Fixed in this pass

| # | Sev | Area | Bug | Fix |
|---|-----|------|-----|-----|
| 1 | HIGH | Tool calls / HITL | Preset auto-approval posted `auto_approved`+`preset` in `response_data`; the permission respond contract allows only `{action,granted,scope}` (+`feedback` on deny) → guaranteed 400, attempt marked done, card stuck pending until expiry (`permissionPresetModel.ts:147`, `hitl.py:127-135`) | Desktop sends only the contract fields; the resolved-with-preset marker stays a local timeline fold (`App.tsx`). Test pins the exact wire key set |
| 2 | HIGH | Tool calls | Cloud MCP App tool calls always failed: renderer always acquired and sent an idempotency key; cloud rejects any key with `cloud_mcp_tool_idempotency_unavailable` (`mcpAppHostBridge.ts:72-87`, `apps.py:46-60,208,334`) | The HTTP projection omits `idempotency_key` from cloud bodies (`runtime.mode === 'cloud'`); local sidecar contract unchanged. Cloud tests now assert zero keys on the wire while local keeps them |
| 3 | MAJOR | Plugins | In-app marketplace install could never reach `ready`: desktop/web demanded `signature.public_key_pem` from the catalog, which redacts it by contract (router test asserts absence). Install button never rendered with real data (`pluginMarketplaceModel.ts:117-132`, `plugin_marketplace_install_service.py:112-116`) | Backend: install accepts requests without signature/provenance and resolves material server-side — signer PEM picked from the trust store by the catalog row's `public_key_sha256`, archive signature pinned by the row's `signature_sha256`, records preserved verbatim so reinstalls stay immutable. Desktop + web parity: availability keys off the redacted anchors, install request omits signature material. New service + router tests cover resolve, missing-row, and digest-drift paths |
| 4 | MAJOR | Agent | Every desktop definition save stamped `max_iterations_explicit=true`, severing tenant 智能体配置 inheritance — update differed from create (`definitions_router.py:583-587` vs `:318-321`) | Update now mirrors create: explicit only when the value differs from `LEGACY_DEFAULT_MAX_ITERATIONS`. Two router tests pin implicit/explicit transitions |
| 5 | MAJOR | Subagent | Desktop cloud `send_message` carried `subagent_id`; the backend handler has no such field, so subagent chips silently routed to the default agent (`useAgentSocket.ts:249`, `chat_handler.py:255-320`) | `composerAgentExecutionContext` emits `subAgentId` only in local mode (where the workspace-core selector is authoritative); cloud chips remain context references and live steering stays on the subagent control panel. Composer tests pin both modes |
| 6 | MAJOR | Workspace | Local project-blackboard status surface demanded an `{items,total}` envelope from `GET /workspaces/{id}/tasks`; workspace-core serves a bare `Vec<PublicWorkspaceTask>` (and so does the cloud route) → guaranteed `local_project_blackboard_tasks_contract_invalid` (`desktopProjectBlackboardTransportV2.ts:331-348` vs core `tasks.rs:127`) | Validator accepts the bare array; the test fixture no longer masks the bug with the envelope shape |
| 7 | MED | Skills | Live forced-skill cards froze at "Matched / 0%": the backend emitted only `skill_matched`; the five lifecycle events existed only as legacy history builders (`react_agent_stream_mixin.py:793-845`) | The forced-skill path now emits `skill_execution_start` after resource sync and `skill_execution_complete` (success + execution_time_ms) at Phase 14. Desktop group model already consumes both; history replay round-trips through `_build_skill_event` |
| 8 | MED | Conversation | `relaxed` preset copy promised "auto-allow low-risk; ask for the rest", but the mapped `automatic` mode denies non-workspace mutations without asking | Copy corrected in both locales + model comment documents the real wire semantics |
| 9 | MIN | Agent | Desktop edit dropped unmodeled `workspace_config` fields (`persona_files`, `shared_files`, `max_size_mb`, `auto_cleanup`, `retention_days`) — backend `from_dict` replaces the object | Draft carries a passthrough of unmodeled keys; the mutation merges them back. Form tests pin the round trip |
| 10 | MIN | Subagent | Live `subagent_ended` with `timed_out`/`pending` statuses was dropped (`subagentLifecycleEnvelope.ts:62-69`) | Mirrors the cloud trace snapshot mapping (`timed_out`→`subagent_run_failed`, `pending`→`subagent_queued`); unknown statuses still fail closed |
| 11 | MIN | Conversation | Stop-flow `cancelled` settlement matched a payload shape the backend never sends (`agentStopResponseModel.ts:47-53`) | Settles on the real `{type:"cancelled",data:{status:"cancelled"}}` shape; legacy boolean alias kept |
| 12 | MIN | Conversation | `STEER_UNSUPPORTED` in the steer rejection set is emitted by no backend (only `STEER_NOT_SUPPORTED`) | Removed from the set; test uses the real code |
| 13 | LOW | Skills | Skill editor lacked the backend's 64-char name cap | Validated as `too_long` |
| 14 | LOW | Skills | Tenant skill catalog hard-capped at 100 (backend allows 500) | Raised to 500 in projection + contract |
| 15 | LOW | Tool calls | Every MCP server edit sent `server_type`+`transport_config`, which the backend treats as a config change → needless runtime reinstall for description-only edits | Identity fields ride only when the type/transport actually changed (or a new credential secret was provisioned) |
| 16 | MIN | Plugins | `upgrade_root_builtin_bundle_v2.py`: bare `StopIteration` when the ROOT desired set lacks the bundle; `--expected-revision 0` mis-parsed as missing | Friendly error + `is not None` checks |

## Pass 4 addendum — user-reported local-conversation failure (2026-09-20)

**Symptom.** A fresh local-mode conversation dies with a raw timeline error
`llm error: model_unconfigured: configure a local LLM provider before starting an agent`
(sidecar `UnconfiguredLocalLlm`, `local_runtime/mod.rs:10164-10177`): the desktop let a run
start that could never succeed and offered no path to fix the state.

**Root cause.** The composer had no notion of local LLM readiness. The sidecar's provider
catalog (`GET /api/v1/llm-providers/`) already reports every field needed to evaluate its own
runtime admission (`is_active`, `credential_configured`, `provider_type`, `base_url`,
`llm_model`), but nothing consumed it before dispatch.

**Fix.**
- `localLlmReadinessModel.ts`: pure predicates mirroring the sidecar admission
  (`localLlmProviderUsable`, `localLlmUnconfiguredFromProviders`) plus a protocol-token matcher
  (`isModelUnconfiguredError`) for the stable `model_unconfigured` constant.
- App (local mode, per conversation): probes the provider catalog once per conversation and again
  on every hash change (App is the persistent root, so returning from settings must re-probe);
  while no provider passes admission the composer is disabled with a localized reason and an
  `authorityNotice`-slot warning with an "Open provider settings" action deep-linking to
  `/tenant/{tenantId}/providers`.
- Timeline decode (`appTimelineEventModel.ts`): error events carrying the `model_unconfigured`
  token set `localLlmUnconfigured`, and `timelineSummary` renders the localized actionable
  explanation (raw payload preserved as evidence).

**Verification.** New `tests/local-llm-readiness-model.test.mjs` (admission matrix, unknown-catalog
honesty, token matching) and an extended `tests/app-timeline-event-model.test.mjs` (decode flag on
matching errors only). Full desktop suite 4861 pass / 0 fail; `build:electron` clean.

## Pass 4 addendum 2 — root cause of the configured-but-unconfigured failure (2026-09-20)

The first addendum hardened the composer for a genuinely unconfigured catalog. The user report
"provider 已配置仍报 model_unconfigured" exposed the real defect in the sidecar's route
resolution — three fail-closed gaps that ignore a healthy tenant-level provider:

1. `llm_for_policy` treated an **unparseable workspace policy** (missing/invalid `roles`) as
   terminal instead of falling back to the tenant default.
2. `llm_for_policy` appended the tenant default **only when the policy had zero targets**; a
   policy with **stale targets** (referencing providers that were deleted/re-created, e.g. from a
   legacy import) produced zero candidates with a non-empty target list and skipped the fallback.
3. `llm_for_unbound_conversation` failed a **stale per-conversation route** terminally instead of
   falling back. Additionally, `selected_provider_route` returned `None` for an unpinned tenant
   with **multiple active bindings** — reachable because auto-select only pins providers created
   with ready credentials and the renderer exposes no pin control.

**Fix (sidecar).** Explicit targets keep priority; the tenant-level runtime default (explicit
selection, else the deterministic first active binding by provider id) is always appended as the
last-resort failover candidate; a stale conversation route now falls back instead of dying. The
system stays fail-closed only when no provider is genuinely usable.

**Tests.** `stale_policy_targets_fall_back_to_the_tenant_default_binding`,
`stale_policy_targets_stay_unconfigured_without_binding`,
`unparseable_policy_falls_back_to_the_tenant_default_binding`,
`unpinned_multi_provider_tenant_resolves_deterministic_default`,
`stale_conversation_route_falls_back_to_the_tenant_default_provider` — sidecar suite 931 pass.
Debug sidecar binary rebuilt so the fix is live for the running desktop.

## Pass 4 addendum 3 — root cause confirmed live, fix verified end to end (2026-09-20)

Running the rebuilt sidecar against the real desktop profile confirmed the deepest root cause
behind "provider 已配置仍报 model_unconfigured":

- The user's catalog had **two** healthy providers (MiniMax, glm-5.2), both `configuration_valid`,
  **neither** runtime-selected. `selected_provider_route` returned `None` for an unpinned
  multi-provider tenant → every conversation failed. Fixed (deterministic fallback).
- Provider delete is a **tombstone** (`desktop_managed_resources.status = 'deleted'`, value_json
  keeps `is_active: true`). `list_runtime_provider_connections` did **not** filter tombstones, so
  on every sidecar restart a deleted provider **revived** into runtime bindings and — with the
  smallest provider_id in the catalog — captured all routing while remaining invisible in the
  settings list. Fixed (filter `status <> 'deleted'`).

**Live verification** (desktop relaunched via `make -C agi-stack run-desktop` with the rebuilt
sidecar, driven through the real sidecar HTTP API):

1. Provider catalog: MiniMax + glm-5.2, both `configuration_valid`, no tombstone revival.
2. New conversation, message `hi` → `user_message` → **real MiniMax assistant reply** →
   `complete`. No `model_unconfigured`, no error.

**Sidecar suite**: 932 pass (adds `deleted_provider_does_not_revive_after_runtime_restart`,
plus policy-fallback and stale-route regression tests).

## Verified correct (no action)

- W4 (prior observation) closed by source inspection: workspace-core's
  `WorkspaceCoreAuthority::Local.as_str() == "local"` matches the desktop local-mode capability
  probe expectation; the cloud platform pins `"cloud"`.
- Workspace endpoints/payloads (CRUD, members, agents, objectives, genes, blackboard, autonomy
  attention, collaboration authority/capabilities/mutations), scope re-observation, and role gates.
- Conversation send/steer/stop ack contracts, socket lifecycle (backoff, heartbeat, cursor resume,
  outbox), history pagination, conversation CRUD, HITL respond v2 (revision + idempotency), all
  five HITL card types, search/pin/export.
- Skill CRUD + import/export/version/rollback routes, forced-skill badge/name matching, ACT/OBSERVE
  converter field coverage, subagent tool-event payloads.
- Marketplace list/approve/revoke/uninstall contracts; local plugin install chain (sidecar routes,
  state machine, digests, control-pipe commands, data-plane credentials, plugin slots).
- Subagent cloud control (HTTP + WS), trace snapshots, run review authority, task-session
  idempotency, plan approval, tenant agent config routes.

## Documented, deliberately not changed

- Dead `buildWorkspaceMutationRequest` export emits paths the cloud policy would reject if ever
  wired (dead code only).
- `If-Match` carries a bare revision integer (non-RFC); both proxies forward it and the authority
  reads `X-Expected-Revision`.
- Desktop 512 KB cloud request ceiling caps workspace file uploads below the backend bound
  (fail-closed, desktop-visible limit).
- Session event head is consumed before the conversation guard during switches; replay/cursor
  recovery bounds the gap.
- Compose-ahead fallback queue is hard-disabled at the production call site
  (`composeAheadFallbackAllowed: false`) — superseded by server-side run-input steer per the
  2026-09-17 roadmap; the send-failure demotion nuance is therefore unreachable.
- `subagent_steered` with-restart renders as killed+new cards (cosmetic grouping).
- Local plugin install UI requires full-permission approval although the sidecar accepts subsets.
- `settings_page` UI slot is registered but has no renderer consumer (native settings page embeds
  the plugin section directly).

## Verification

- `cargo test -p agistack-desktop-sidecar`: 926 pass (no Rust changes in this pass).
- Desktop `pnpm test` (with real sidecar + workspace-core binaries): 4857 pass / 1 skip.
- `pnpm run build:electron` (tsc strict, main+preload+renderer): clean.
- Backend targeted: marketplace service+router, agent definitions router, messages router,
  ReAct components, forced-skill processor — 120+21 pass; `ruff` and `mypy` clean on changed files.
- Web: `tsc --noEmit` clean; prettier clean; affected vitest suites 10/10.
