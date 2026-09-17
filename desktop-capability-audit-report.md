# Desktop Client Capability Audit — agi-demos

Scope: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop` (React renderer `src/`, Electron `electron/`, Rust sidecar `apps/desktop/sidecar` = crate `agistack-desktop-sidecar`), cross-checked against web (`web/src`) and backend (`src/infrastructure/adapters/primary/web`). Read-only audit; nothing modified. Note: exploration was cut short by a step limit; un-audited areas are listed at the end.

Architecture context that shapes nearly every finding: the desktop has two runtime modes. **Cloud mode** talks to the Python backend over HTTP + a native-bridged WebSocket (`src/api/cloudSocketBridge.ts`). **Local mode** talks to the Rust sidecar over loopback HTTP, which implements a curated subset of the backend API and returns structured `501` fail-closed envelopes (`contract_version: desktop-local-route-parity-v1`, `reason_code`) for everything else (`sidecar/src/local_runtime/parity_routes.rs:404-421`). Most "missing" capabilities below are this deliberate contract, not accidents.

## Summary verdicts

| Area | Verdict |
|---|---|
| Workspace | Largely complete; no confirmed bugs found in audited paths |
| Simple chat | Socket layer is robust (backoff, cursor replay, outbox, dedupe); one suspected subscription gap |
| Skills | CRUD/listing/triggering present both modes; evolution/import-zip fail-closed locally by design |
| Plugins | Renderer sandbox correctly isolated; V1 protocol cleanly retired with 410 migration errors |
| Tool calls / HITL | All 4 HITL types + a2ui_action wired; env_var encryption is server-side so desktop plaintext POST is correct; local env_var HITL fail-closed (latent) |
| Agent & SubAgent | SubAgent steer/kill control matches backend contract exactly; execution-selection persistence is local-only by design |

## Confirmed bugs

None confirmed in the audited paths. Every suspicious path I chased (run-input promote, subagent control, HITL respond, plan tasks, workspace-context switch, MCP apps proxy, cron-jobs) had a matching backend or sidecar route.

## Suspected issues (need runtime confirmation)

1. **Chat — subscription gap for messaged-but-inactive conversations** (degraded, suspected).
   `sendAgentMessage` adds the conversation to `subscribedConversations` but does not send a `subscribe` frame on the already-open socket; subscribe frames only go out via the active-conversation transition effect or on reconnect. `agi-stack/apps/desktop/src/hooks/useAgentSocket.ts:559-576` vs `538-557`, `599-625`. If the backend only streams conversation events to explicitly subscribed sessions, background conversations the user messaged would miss live events until a reconnect. Correct behavior: send `subscribe` immediately when adding a new id, mirroring `subscribeConversation`.

2. **Chat — steer UX degrades to a 10-second stall in practice** (degraded, predictable).
   The compose-ahead steer protocol is a frontend-implemented draft the backend does not implement: backend WS handlers cover `send_message`/`stop_session` (`src/infrastructure/adapters/primary/web/websocket/handlers/chat_handler.py:247-256`) and SubAgent-scoped `steer`/`kill_run` (`.../control_handler.py:56,253`), but no `steer_message`. Desktop sends it (`useAgentSocket.ts:124-130, 282-311`) and falls back to queue after a 10 s ack timeout (`docs/steer-protocol-draft.md` §4, self-declared "草案/待后端评审"). Until the backend lands, every steer attempt waits 10 s then becomes a queued message. Documented, but user-visible today.

3. **Session — stage stepper never renders** (degraded, documented residual risk R4).
   `buildSessionDetailViewModel` hard-sets `stage` to `'unavailable'`, so the stepper is permanently absent. Recorded in `agi-stack/apps/desktop/docs/status-honesty-audit.md` (R4, line 47). Not misleading, but the capability does not exist.

4. **Sidebar/workspace tree — stale "running" status during disconnect** (cosmetic/degraded, documented R1).
   Tree status dots keep the last known run status until the server watchdog marks the run `disconnected` and the cursor resubscription replays it. `docs/status-honesty-audit.md` line 44; model at `src/features/workspace/workspaceTreeModel.ts`.

5. **Composer stop button while disconnected** (cosmetic, documented R2).
   Stop remains visible during socket outage; click returns a `socket_unavailable` error rather than silently failing. `docs/status-honesty-audit.md` line 45; `src/features/chat/ChatPanel.tsx`.

## Known-by-design limitations (verified as intentional contracts)

1. **Local-mode fail-closed route set.** Sidecar returns structured 501s for: workflow patterns, genes/gene market, event ledger, channel plugins (`not_applicable`), ACP external agents, subagent templates/filesystem import, skill evolution, skill zip import. `sidecar/src/local_runtime/parity_routes.rs:62-217`, reason-code mapping at `288-354`. Plugin protocol V1 routes return `410 plugin_protocol_v1_retired` with `migration_target: /api/v1/plugin-marketplace` (`221-267`). This matches the QA.md parity-completion note that "operations without local authority remain structured unavailable by contract".

2. **Local mode has no isolated sandbox / remote desktop / sandbox exec.** `ensure_sandbox` and `start_desktop` return 501 "isolated local sandbox/desktop is not configured" (`sidecar/src/local_runtime/mod.rs:9154-9173`); `sandbox_execute` returns 501 (`mod.rs:9562-9572`); the desktop proxy serves a static "local mode uses the native Electron window" page. Local file views instead map a virtual `/workspace` root onto the native workspace with path-escape rejection (`sidecar/src/local_runtime/parity_routes/sandbox_files.rs:31-55, 306-338`; renderer root selection at `src/features/sandbox/useSandboxRuntimeSurface.ts:280`). Cloud mode has the real KasmVNC/terminal/file stack (QA.md Wave A).

3. **env_var HITL responses are fail-closed in local mode.** Sidecar rejects them with 501 `local_secure_env_response_unavailable` (`sidecar/src/local_runtime/mod.rs:7766-7775`, with a no-persistence regression test at 18860-18905). Latent rather than live: nothing in the local runtime constructs `HitlKind::EnvVar` requests outside tests, so the card should never appear locally. In cloud mode the desktop correctly posts plaintext `response_data`; the encryption requirement (`response_data_encrypted`, `src/infrastructure/agent/hitl/utils.py:27, 415-435`) applies to the Redis stream hop, which the HTTP endpoint performs server-side (`routers/agent/hitl.py:858` via `serialize_hitl_stream_response`). The env_var form (`src/features/chat/HitlResponseCard.tsx:512-569`, `hitlResponseCardModel.ts:303-321`) matches the backend ingress validator (`hitl.py:97-158`).

4. **Execution-selection persistence is local-only.** Composer catalog only wires `readExecutionSelection`/`updateExecutionSelection` in local mode (`src/features/chat/desktopChatComposerCatalogClientV2.ts:41-60`), and the hook is explicitly gated (`src/features/chat/ChatPanel.tsx:2151-2156`, comment "local-runtime authority; enable only in local mode"). Not a web divergence: `execution_selection` does not exist in `web/src` or the backend at all — it is a desktop-local-runtime concept (sidecar `execution_selection.rs`). Per-message agent/skill/subagent pinning still works in cloud mode via the `send_message` payload fields (`useAgentSocket.ts:233-251`; web equivalent `web/src/stores/agent/messageSendActions.ts:294`).

5. **Cloud renderer credential gate.** Cloud surfaces fail closed with `renderer_credential_required` unless protocol-v2 data-plane grants were imported at startup (`ELECTRON.md:19-38`). Dev provisioning is automated via `agi-stack/scripts/ensure-desktop-grants.sh`; this was the 2026-09-15 QA fix (QA.md:13-24).

6. **Changes review panel scope toggle not shipped.** "This run vs whole session" scoping is impossible to derive truthfully from the current snapshot contract; deliberately not shipped rather than faked. `agi-stack/apps/desktop/docs/changes-review-gaps.md` (gap 1); per-file revert/stage pending sandbox git write access (gap 2).

7. **Release pipeline is draft-only / package-artifacts-only.** Tag CI verifies signing/notarization/digests but never installs, launches, or applies a real update; Wave 8 gates pending. `ELECTRON.md:97-137`, QA.md:75-85. Not a client capability bug, but the audit's "broken/stubbed" brief should record it.

## Verified-correct highlights (for contrast)

- **Socket resilience**: exponential backoff capped at 15 s (`useAgentSocket.ts:1069-1071`), heartbeat + 60 s stale watchdog (827-841), cursor-based replay via `from_time_us`/`from_counter` (1051-1067) matching backend `subscription_handler.py:324-346`, event dedupe by event-id/cursor (1087-1093), bounded outbox with ack/`MESSAGE_ID_CONFLICT` settlement (445-491).
- **Socket bridge fail-closed**: strict event-shape validation, opaque-origin transport, synthetic `1006` close on any contract violation (`src/api/cloudSocketBridge.ts:224-289`).
- **SubAgent control**: desktop cloud client contract-checks the registry snapshot and receipt (`src/features/chat/cloudSubagentControlClient.ts:18-88`); routes match backend `subagent_execution_control.py:89-112`; WS path has 10 s ack timeout and idempotency-key correlation (`useAgentSocket.ts:639-683`).
- **Plugin renderer sandbox**: iframes use `sandbox="allow-scripts"` with `srcDoc` (`src/features/chat/PlatformPluginConversationSlots.tsx:151-162`); bridge rejects messages unless `source === frameWindow` and `origin === 'null'` (`desktopConversationRendererBridgeV2.ts:126-133`). Artifact previews use `sandbox=""` for HTML/SVG (`ArtifactPreviewSurface.tsx:151-156`). CSP inline-bootstrap pinning fixed 2026-09-15 with a hash-sync test (QA.md:30-35).
- **HITL coverage**: all four types plus `a2ui_action` (`src/types.ts:128-133`); respond path validates request status/kind/revision client-side before POST `/api/v1/agent/hitl/respond` (`App.tsx:2702-2757`, `api/client.ts:1530-1531`); terminal runs leave no respondable cards (status-honesty F4 fix).
- **Automations**: desktop uses `/api/v1/projects/{id}/cron-jobs*` (`api/client.ts:531-628`) which exists in backend `routers/cron.py:52`; local mode has a full sidecar automation stack (leases, fencing, HITL continuation, replay-safe Run Now) per QA.md Wave B.

## Not yet audited (step limit reached)

- Workspace selection/switching UI flow end-to-end (`WorkspaceDock.tsx`, `projectWorkspacesController.ts`, `WorkspaceContextState.tsx` consumers) and workspace-bound route guards in `DesktopProductionRouter`.
- Chat history replay/pagination correctness (`loadConversationTimeline`, `sessionTimelinePaginationModel.ts`) and error-state rendering in `ChatPanel.tsx` (3379 lines, only partially read).
- Plugin marketplace install/uninstall/update flows (`localPluginClient.ts`, sidecar `local_plugin_installations_v2.rs`, `platform_plugin_marketplace_v2.rs`) and MCP app supervisor lifecycle (`sidecar .../mcp_supervisor`).
- Tool-call timeline rendering details (`ChatTimeline.tsx`, tool-result renderer bridge) and permission admission v2 internals (sidecar `authorized_tool_host.rs`, `tool_authority.rs`).
- Automation editor/detail UI, run history views, task execution sessions (`features/task`, backend `task_sessions.py`).
- Electron main process (IPC allow-list, window/navigation guards, updater path) — `electron/` was listed but not read.
- Voice call/transcription runtime beyond route existence, and the A2UI surface registry.
- Electron main ↔ sidecar grant provisioning failure modes beyond ELECTRON.md documentation.
