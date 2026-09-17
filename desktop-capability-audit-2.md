# Desktop Client Capability Audit — Pass 2 (agi-demos)

Scope: the seven areas **not** covered by `desktop-capability-audit-report.md` (pass 1). Read-only; nothing modified. Cross-checks against backend (`src/infrastructure/adapters/primary/web`, `src/application/schemas`) and web (`web/src`) where relevant.

## Verdict summary

| # | Area | Verdict |
|---|---|---|
| 1 | Workspace selection/switching UI + route guards | Correct |
| 2 | Chat history replay/pagination + error states | Correct; two cosmetic issues |
| 3 | Plugin marketplace install/uninstall/update + MCP supervisor | Correct; one capability gap (no client install UI) |
| 4 | Permission admission v2 (sidecar internals vs renderer) | Correct; two design notes |
| 5 | Automation editor/detail/run history + task sessions | Correct |
| 6 | Electron main (IPC allow-list, navigation guards, updater, sidecar) | Correct (partial file coverage — see unaudited list) |
| 7 | Voice runtime + A2UI surface registry | Correct; two minor notes |

No confirmed bugs found in this pass.

## 1. Workspace selection/switching — correct

- `WorkspaceDock.tsx` is purely presentational and covers every tree state (`refreshing`, `stale-error`, `deferred`, `loading`, `error`, `empty`) with retry affordances and focus restoration after lifecycle dialogs. `agi-stack/apps/desktop/src/features/workspace/WorkspaceDock.tsx:219-351`, dialog focus return at `:165-177`.
- Workspace selection commits a new runtime config, resets conversation session/timeline/task signals, clears the production-route hash, and refreshes the runtime. `src/App.tsx:4347-4366`.
- Tenant/project switching goes through the workspace-context authority: revision-checked `switchWorkspaceContext` with an idempotency key, request-currency guards, and a post-switch mismatch check that throws if the returned context does not match the requested selection. `src/App.tsx:6660-6730` (`switchWorkspaceContext` call at `:6698`).
- Create/update workspace mutations re-validate the scope (tenant/project/epoch/contextRevision) before and after the network call and throw `WorkspaceCreateScopeChangedError` on drift. `src/App.tsx:4379-4399`.
- Production router boundaries render explicit `forbidden`/`unavailable`/`error`/`malformed`/`not_found` states with reason codes, and Escape/return-to-workbench recovery. `src/features/navigation/DesktopProductionRouter.tsx:227-317`, reason mapping `:319-357`.
- Scope switching inside the route host is transactional: abort controller + revision guard, permission-snapshot scope match, and authority-revision staleness rejection (`desktop_route_permission_revision_stale`). `src/features/navigation/desktopHashRouteHost.ts:268-328`.
- The project-workspaces route module refuses to render when the binding scope diverges from the route context (`project_workspaces_route_binding_scope_mismatch`) and falls back to an inert controller on invalid context. `src/features/project-workspaces/projectWorkspacesRouteModule.tsx:82-94, 106-138`.
- The controller serializes loads with abort + request-revision discipline and classifies failures (403 → forbidden; 0/501/503 → unavailable; retryable only for 408/425/429/5xx). `src/features/project-workspaces/projectWorkspacesController.ts:52-113, 129-153`.

Observation (not a bug): the V2 client reports `availability: 'degraded'` with reason `desktop_project_workspace_lifecycle_partial` / `local_workspace_lifecycle_partial` on every successful list, so the workspaces page always shows a partial-lifecycle reason badge even when healthy. Conservative honesty posture, but it permanently labels a working state as degraded. `src/features/project-workspaces/projectWorkspacesV2Client.ts:51-58, 156-160`.

## 2. Chat history replay/pagination — correct

- Backward pagination sends `before_time_us`/`before_counter` from the first cursor. `src/App.tsx:2650-2656`. Backend honors an exclusive tuple comparison `event_time_us < before OR (equal AND counter <)`. `src/infrastructure/adapters/secondary/persistence/sql_agent_execution_event_repository.py:488-493`, cursor computation `src/infrastructure/adapters/primary/web/routers/agent/messages.py:1529-1545, 1578-1612`.
- Race safety: monotonically increasing request id + scope epoch guard on both full load and earlier-page load; stale completions are dropped. `src/App.tsx:2534-2544, 2633-2643`.
- Stall guard: if a page returns no new items or a non-earlier cursor, pagination stops instead of looping forever. `src/features/session/sessionTimelinePaginationModel.ts:25-46`.
- Error rendering: `ChatTimeline` shows `state.error` in an assertive alert with a retry button that replays `onLoadEarlier` when items exist, else full `onRetry`; subagent-trace failure is a separate non-blocking banner. `src/features/chat/ChatTimeline.tsx:342-369`. Retry works after a failed earlier-page load because `failEarlierTimelinePage` retains `firstCursor` and clears `loadingEarlier`. `sessionTimelinePaginationModel.ts:48-57`.

Cosmetic issues:
1. A transient network failure on "load earlier" sets `hasMore: false` (`sessionTimelinePaginationModel.ts:56`), so the inline "load earlier" button (`ChatTimeline.tsx:370` requires `!state.error && hasMore`) disappears; recovery is only via the error banner. Degraded but recoverable.
2. A pagination stall (end-of-history anomaly) is surfaced through the same red `role="alert"` error path as a real failure (`session.earlierHistoryNoProgress`), conflating a benign condition with an error. `src/App.tsx:2667-2669`.

## 3. Plugin marketplace + MCP supervisor — correct

Local plugins (`.mspkg`):
- Renderer client strictly validates every response field (reference/scope echo, status transitions per action, activation/authorization invariants, uniqueness) and rejects scope or identity drift. `src/api/localPluginClient.ts:106-176`. Archive pre-validation: `.mspkg` extension, 0 < size ≤ 64 MiB. `:252-263`.
- Routes match the sidecar exactly: `GET/POST /api/v1/local-plugins/v2/installations[/inspect|/import|/:bundle_id/:action]`. `src/api/localPluginClient.ts:39, 112-115` vs `sidecar/src/local_runtime/local_plugin_routes_v2.rs:141-153`.
- Sidecar re-verifies the signed bundle on every activation (bytes + approvals persisted, never a reusable proof), enforces declared-permission subset, and performs an atomic upsert on import — re-importing the same `bundle_id` is the update path (no separate update UI). `sidecar/src/local_plugin_installations_v2.rs:56-95`.

Cloud marketplace:
- Desktop implements list (`?include_revoked=true`) and uninstall only. `src/api/client.ts:1709-1738`. This matches web scope (`web/src/services/pluginMarketplaceService.ts:20-44`).
- Capability gap (by design, but worth recording): the backend also exposes `POST /api/v1/plugin-marketplace/packages/{id}/install`, `/approve`, `/revoke` (see `src/tests/unit/routers/test_plugin_marketplace_router.py:196-367`), and no client — desktop or web — surfaces install/approve/revoke. Marketplace acquisition must happen out-of-band (backend desired-bundle sync).
- In local mode the sidecar proxies marketplace list/uninstall to the cloud authority with bearer credential and fail-closed 502/503 envelopes on upstream or authority failure. `sidecar/src/local_runtime/platform_plugin_marketplace_v2.rs:46-110`.

MCP app supervisor (sidecar):
- Full lifecycle: CRUD with revision checks, health, startup recovery (`prepare_startup_recovery` abandons unbound credential stages and marks enabled servers recovery-pending), vault-backed credential provisioning with header-value validation, and leased, idempotency-keyed tool calls with request-hash binding. `sidecar/src/local_runtime/mcp_supervisor/mod.rs:489-560, 672-704`.
- Notes: `recover_all_enabled` spawns a detached task and recovery errors are deliberately swallowed (`let _ = ...`), with state tracked via `mark_enabled_recovery_pending` — acceptable best-effort recovery, but failures are invisible outside the stored status. `mod.rs:489-527`.

## 4. Permission admission v2 — correct

- Grant primitives are exact-match (run, plan version, run revision, environment, tool, canonical target digest, canonical input digest), single-consumption with use-limit/expiry, and fully unit-tested, including key-order-independent canonical digests and recursive sensitive-field redaction. `sidecar/src/local_runtime/tool_authority.rs:155-215, 433-478`.
- The run-scoped host gates dispatch on the run's permission profile (`read_only`/`workspace_write`/`full_access`) plus a run-scoped once-permission cache; historical workspace grants cannot broaden the plan's chosen profile. `sidecar/src/local_runtime/authorized_tool_host.rs:114-129`.
- Durable invocation lifecycle (`Prepared → Executing → Completed/Failed/UnknownOutcome`) with replay semantics: a completed identical invocation returns a "replayed" result instead of re-executing; unknown outcomes require human inspection. `authorized_tool_host.rs:315-341`.
- Renderer ↔ sidecar contract match verified:
  - Allow-once: renderer submits `{action:'allow', granted:true, scope:'once'}` (`src/features/chat/HitlResponseCard.tsx:438`); sidecar consumes exactly that shape (`sidecar/src/local_runtime/mod.rs:8657-8676`).
  - Allow-always: renderer submits `{action:'allow_always', granted:true, scope:'workspace_tool'}` (`HitlResponseCard.tsx:457`); sidecar builds a persisted `WorkspaceToolGrant` from exactly that shape (`mod.rs:8603-8644`, validation tuple at `:8435`), with list/revoke routes (`mod.rs:3103-3107`).
  - Browser-origin/full-CDP consents: persisted scopes (`site`/`all`/`decline`) go to grant tables; `once` stays in run-scoped memory, never persisted. `mod.rs:8078-8097, 8687-8726`.

Design notes (not bugs):
1. For mutating tools under an approved profile, the host **synthesizes** a self-issued per-invocation `PermissionGrant` (`local-profile-grant-{digest}`, use_limit 1, 5-minute TTL) to feed the audit ledger (`authorized_tool_host.rs:282-298`). The real authorization decision is the profile/once-cache check; the durable grant machinery from `tool_authority.rs` ("authorization approved by the human or policy layer") is used as an audit record, not as an external grant. Behavior is safe, but the naming implies stronger provenance than exists.
2. A once-permission is consumed before the replay check (`authorized_tool_host.rs:311-313`): repeating an identical already-completed call burns the user's one-shot approval without executing anything, forcing re-approval for a genuine retry. Edge case, predictable.

## 5. Automations + task sessions — correct

- Run Now is revision-guarded and replay-safe: `contract_version: 2`, `expected_revision >= 1`, idempotency key reused per attempt fingerprint, and any non-definite outcome (network failure, 5xx, unparseable body) raises `AutomationRunOutcomeUnknownError` so the UI never falsely reports failure or invites duplicate submission. `src/features/automations/automationClient.ts:38-86, 152-218`.
- Backend schema matches exactly, including `contract_version: Literal[2]`, `extra="forbid"`, and the idempotency pattern `^[!-~]+$` (mirrored by the renderer's visible-ASCII check). `src/application/schemas/cron.py:147-155`, endpoint `src/infrastructure/adapters/primary/web/routers/cron.py:315-403` with 412 revision and 409 idempotency-conflict handling (`:357-380`).
- Detail/run-history views are capability-driven (run/edit/toggle/delete each checked against the capability envelope plus runtime capability) and run history loads are abortable with an error state. `src/features/automations/AutomationDetail.tsx:64-92`, `AutomationsPage.tsx:128-149`; backend runs route `cron.py:406-430`.
- Task sessions: renderer POSTs `/api/v1/tenants/{t}/projects/{p}/task-sessions` (`src/api/client.ts:782-801`); backend router exists with a strict schema requiring `idempotency_key` (`src/infrastructure/adapters/primary/web/workspace_core_task_sessions.py:45`, `routers/task_sessions.py:100-107`). The client's single silent retry on transport failure (`client.ts:794-799`) is safe because the idempotency key makes the POST replay-safe; response is scope-validated by `requireCreateTaskSessionResponse`. Creation-attempt fingerprinting/dedup lives in `src/features/task/newTaskSessionModel.ts:81-193`.

## 6. Electron main process — correct (partial coverage)

- Renderer window is locked down: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, `webSecurity: true`, custom protocol for production. `electron/main/index.ts:1141-1157`.
- Navigation policy denies all `window.open` (secure http(s) targets are handed to `shell.openExternal`) and blocks `will-navigate` to anything but the dev origin or the exact production renderer protocol host (no credentials/port). `index.ts:1088-1119`.
- IPC surface is an explicit `case` allow-list over a single command channel plus native-file/update channels; unknown commands throw `desktop command is not supported`. Identity-mutating sidecar commands (`trusted_session_clear`, `local_trusted_session_save/clear`, `platform_plugin_authority_select_v2`) run inside an authority transition that cancels pending cloud auth before and after. `index.ts:626-868`, `845-866`, handler registration `:1360-1366`.
- Media permissions are granted only to the main window, only from the trusted renderer origin, only for audio. `index.ts:1059-1086`, policy in `mediaPermissionPolicy.ts`.
- Renderer delivery ownership is retired on main-frame navigation and window close, and cloud request/socket executions are cancelled per owner. `index.ts:1168-1179`. `RendererDeliveryAdmissionV2` suspends delivery creation/submission during identity transitions. `electron/main/rendererDeliveryAdmissionV2.ts:1-18`.
- Updater: disabled in dev and for externally managed installs (deb/rpm/AppImage-etc. via `resolveUpdateRecoveryInstallation`); signed feed + recovery snapshot/journal/helper machinery otherwise. `electron/main/updater.ts:53-89`. Consistent with pass 1's note that the release pipeline is still package-artifacts-only (no real update application is exercised in CI).
- Sidecar supervisor: private stdio control pipe, bootstrap secret written once via stdin and proven by HMAC in the readiness response, never in argv/env; bounded restart backoff (250ms→10s, max 4 attempts, 60s stability reset) and 40s shutdown timeout. `electron/main/sidecarSupervisor.ts:15-21, 95-101`. Data-plane credential env vars are stripped from the child environment. `:72-87`. Grant provisioning failures fail closed with explicit `sandbox desktop grants unavailable` / `desktop sidecar is unavailable` errors rather than silent degradation (`index.ts:654, 847`).

## 7. Voice runtime + A2UI registry — correct

Voice:
- Connection builder targets `/api/v1/voice/chat` over ws/wss with `project_id`/`conversation_id` query params, native Electron transport when available, subprotocol auth (`memstack.auth`) otherwise. `src/features/chat/voiceTranscriptionModel.ts:55-89`. Matches the backend endpoint, including the mandatory first `voice_config` message (10s timeout) and the identical default speaker. `src/infrastructure/adapters/primary/web/routers/voice_websocket.py:53-105`; client config at `src/features/chat/voiceCallRuntime.ts:220` and `voiceTranscriptionRuntime.ts:138`. Backend auth accepts Authorization header, subprotocol, or legacy token (`websocket/auth.py:37-57`), so both desktop transports are covered.
- A strict contract checker pins URL origin/path, exact query keys, protocols, and scope before a session may start. `src/plugins/desktopVoiceSessionContractV2.ts:72-111`.
- Local mode fails closed with `availability: 'local_runtime'` and the composer surfaces a per-reason unavailable label instead of a dead button. `voiceTranscriptionModel.ts:56`, `src/features/chat/ChatPanel.tsx:2232`. No local-mode voice route exists in the sidecar (confirmed absent from `parity_routes.rs`), consistent with the fail-closed contract.

A2UI:
- Surface replay validates JSONL deltas with safety checks and rejects unknown component kinds (`a2ui_component_unsupported`), unsafe payloads, and malformed definitions. `src/features/chat/a2uiSurfaceModel.ts:329-352`.
- Outgoing actions are built only when request id, authority revision, idempotency key, and allowed-actions are present, and are validated against the persisted allowed-action membership before dispatch. `src/features/chat/DesktopA2UISurface.tsx:49-97`, `a2uiAction.ts`. This matches the backend's server-side `source_component_id` + `action_name` membership validation (per AGENTS.md HITL rules).
- Desktop-only components (Badge/Radio/Table/Progress) are registered idempotently. `a2uiDesktopRegistry.tsx:14-22`.

Minor notes:
1. `ensureDesktopA2UIRegistry()` runs during render (`DesktopA2UISurface.tsx:57`) — a render-phase global mutation. Idempotent and harmless today, but fragile under concurrent React rendering.
2. Kind remapping `Checkbox→CheckBox`, `Select→MultipleChoice` (`DesktopA2UISurface.tsx:113-122`) indicates naming drift between backend surface payloads and the vendored `@copilotkit/a2ui-renderer` catalog; any future drift in other kinds fails closed (unsupported → explicit state), so this is visible rather than silent.

## Suspected issues (need runtime confirmation)

None new in this pass beyond the pass-1 list. The closest candidates are the two cosmetic pagination behaviors (area 2) and the once-permission consumption-on-replay edge (area 4, note 2) — all deterministic from code, low impact.

## Partially audited / left for a future pass

- `electron/main/cloudRequestPolicy.ts` (1450 lines) and the per-domain endpoint policies (`cloud*EndpointPolicy.ts`) — only their wiring into the command allow-list was verified, not per-route coverage.
- `electron/main/automaticUpdateLoop.ts`, `updateRecovery*.ts` internals (journal format, helper launch correctness) — not read.
- `mcp_supervisor/{stdio,http,websocket,http_session,tool_call_lease}.rs` transport internals — only the supervisor façade was read.
- `authorized_tool_host.rs` browser/CDP credential-fill paths (`call_browser` etc.) — skimmed, not fully traced.
- `AutomationEditorDialog.tsx` (410 lines) form↔schema field mapping — not read; the mutation contract beneath it was verified instead.
- `features/task/NewTaskFlow*.tsx` stage UI — model and client contract verified; visual states not rendered.
- `WorkspaceOverview.tsx` consumers of `WorkspaceContextState` — usage confirmed (`WorkspaceOverview.tsx:176-248`); props wiring not traced line-by-line.
- Local-mode automation sidecar stack (leases/fencing) — covered by pass 1 per QA.md Wave B; not re-verified.
