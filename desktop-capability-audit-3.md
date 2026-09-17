# Desktop Capability Audit — Pass 3 (leftover surfaces)

Scope: the six areas left unaudited by passes 1–2 (`desktop-capability-audit-report.md`, `desktop-capability-audit-2.md` §"Partially audited / left for a future pass"). Read-only; no source files modified.

## Verdict summary

| # | Area | Verdict |
|---|------|---------|
| 1 | `electron/main/cloudRequestPolicy.ts` + per-domain endpoint policies vs backend routers | Correct (sampled routes all exist with matching methods; fail-closed throughout) |
| 2 | Updater internals (`updater-transaction.mjs`, `smoke-update-recovery.mjs`, `automaticUpdateLoop.ts`) | Correct; three design notes |
| 3 | MCP sidecar transports + `tool_call_lease.rs` | Correct; two design notes |
| 4 | `authorized_tool_host.rs` browser/CDP paths | Correct; one edge-case note |
| 5 | `AutomationEditorDialog` field mapping vs cron-jobs API | Field mapping correct; **one confirmed UX bug** (webhook delivery is a dead option) |
| 6 | `NewTaskFlow.tsx` + `WorkspaceOverview` props wiring | Correct; two minor notes |

No confirmed logic bugs in areas 1–4, 6. One confirmed user-facing dead option in area 5.

## 1. cloudRequestPolicy per-route internals — correct

Checked every literal path and every segment-family in `cloudRequestPolicy.ts` and the seven `cloud*EndpointPolicy.ts` files against `src/infrastructure/adapters/primary/web/routers/`.

- All referenced route families exist in the backend: `workspace-context` (`workspace_context.py:28,58,80` — GET "" and POST `/switch` match), `graph-stores`/`retrieval-stores` (`graph_stores.py:31,69-222`: `/types` GET, `/test` POST, collection GET/POST, `/{id}` PUT/DELETE, `/{id}/test` POST — exactly the set admitted by `authorizeBackendEndpoint`, `cloudRequestPolicy.ts:880-914`), `projects/{id}/playbooks|reflection-verdicts` (`reflection.py:76,121`), `projects/{id}/activity/read-state` PUT (`project_my_work.py:148`; the 7-segment check at `cloudRequestPolicy.ts:361-363` parses correctly), `projects/{id}?tenant_id=` (`projects.py:635-641`), `projects/?page&page_size&tenant_id` returning `total/page/page_size/projects/owner_ids` (`projects.py:456,628-631`), `tenants/` (`tenants.py:43,222`), `projects/{id}/stats` (`projects.py:1087`), `projects/sandboxes` (`project_sandbox.py:2085`), `users/me` GET/PUT (`auth.py:577,621`), `auth/force-change-password` (`auth.py:473`), `auth/device/approve` POST (`auth.py:866`), `agent/runs/{id}/summary` (`agent/run_review_authority.py:216`).
- Backend `page_size` caps at 100 (`tenants.py:222`, `projects.py:456`); desktop pins `IDENTITY_CATALOG_PAGE_SIZE = 100` (`cloudRequestPolicy.ts:143`) — exactly at the cap, no 422.
- Fail-closed posture is consistent: default-deny endpoint authorization (`cloudRequestPolicy.ts:877`), origin pinning + `redirect: 'manual'` + `credentials: 'omit'` (`:962-988`), response size/MIME/UTF-8 contract enforcement with body cancel on violation (`:1188-1247`), protected-credential byte-scan of responses (`:1043, 1084, 1211`), workspace/tenant/project/conversation/MCP-server scope re-observation before dispatch (`:1266-1339`), and revision-drift rejection in catalog pagination (`:488-491`).
- The one swallowed error is deliberate and narrow: transport failure on `PUT …/activity/read-state` is converted to a synthetic 503 with reason `activity_read_state_transport_unavailable`, after re-checking abort (`:356-377`). Read-receipts are best-effort; this does not mask mutations.

Observation (not a bug): a renderer with a stolen request slot can only reach allow-listed endpoints, but the identity catalog loader treats any total-count change between pages as fatal (`:489-491`) — under a concurrently growing tenant catalog, session projection can fail spuriously until counts settle. Conservative, self-healing on retry.

## 2. Updater internals — correct, three notes

`scripts/updater-transaction.mjs`:
- `applyUpdateWithRollback` is a sound same-filesystem rename transaction: sibling/distinct path enforcement (`:54`), real-directory + no-symlink checks via `lstat` (`:16-21`), backup→staged swap with rollback on apply failure (`:63-69`), strict `=== true` validation result (`:73`, fail-closed on thrown validators), and a `restorePreviousInstallation` that re-restores the backup even if the first rollback rename partially failed, preserving both paths for operator recovery (`:23-39`).

`scripts/smoke-update-recovery.mjs`:
- Exercises the real sidecar binary end-to-end: prepare → snapshot hash capture → candidate journal (phase applying) → helper spawn → expired-deadline journal (phase verifying) → recovery helper run → asserts version rollback, journal `recovered`, and candidate process death (`:189-198`). Private files written `0o600`, dirs `0o700`; cleanup in `finally` kills the candidate and removes the temp root (`:200-205`). No swallowed assertions.

`electron/main/automaticUpdateLoop.ts`:
- Recovery journal load failure at startup → `failed/update_recovery_journal_invalid` state, still allowing manual `check` (`:142-158`) — no silent never-update.
- Interval only fires `check` when `allowedActions` includes it (`:377-382`), and the initial check is skipped when a recovery record exists (`:384`) so a mid-flight recovery is never clobbered by a fresh check; `check()` clears the journal *before* contacting the feed (`:301-306`), consistent with the verifying/restart handshake.

Notes (not bugs):
1. Contract-violation failures are non-retryable with empty `allowedActions` (`update_available_contract_invalid` `:199`, `update_download_progress_contract_invalid` `:231`, `update_downloaded_contract_invalid` `:246`): one malformed event from electron-updater disables auto-update until app restart. Fail-closed, but a single bad progress event is enough.
2. The `error` event handler discards the electron-updater error object and reports a generic string (`:281-284`) — diagnostics loss, deliberate.
3. After a `recovered` startup, the first update check waits for the next 6-hour interval tick (`:384`); updates are delayed, never skipped.

## 3. MCP sidecar transports + tool_call_lease — correct, two notes

`tool_call_lease.rs` lease lifecycle traced end-to-end:
- Reservation is transactional (`TransactionBehavior::Immediate`, `:143`) with exact idempotency binding (server_id + request_hash mismatch → `idempotency_conflict`, `:163-167, 205-207`), replay from either the receipts table or a completed operation row (`:145-173, 208-216`), fence-token CAS on lease re-acquisition after expiry (`:253-279`), and status-machine transitions guarded by lease_token + fence_token (`update_tool_call_status` `:336-372`, `complete_tool_call` `:374-429` — completion also writes the replay receipt in the same transaction).
- Error paths propagate honestly: dispatch/validation/completion failure marks the operation `indeterminate` and returns `local_mcp_tool_call_indeterminate` (`:81-106`); an expired `dispatched` lease observed by a later caller is converted to `indeterminate` (`:221-245`), so the original caller's later `complete_tool_call` fails the status guard and also goes indeterminate — no double-completion, no lost-update replay.
- `lease_duration` is clamped to ≥ initialize + request timeout + 2 s (`:40-49`), so a healthy in-flight call cannot expire under its own waiter.

Notes:
1. Indeterminate is terminal per idempotency key: a transient transport error permanently poisons that key (retry requires a new key). Fail-closed and intentional, but callers must know not to retry with the same key.
2. All `let _ = …` sites in `stdio.rs:266-267` (kill/wait on teardown), `websocket.rs:284` / `http_session.rs:79` (shutdown timeouts), `mod.rs:495-508` (startup recovery) and `mod.rs:802,823` (best-effort error recording) are cleanup/recovery paths where the error has no safer consumer — consistent with the pass-2 assessment of `recover_all_enabled`.
3. Lease expiry uses wall-clock `now_millis()`; a large clock jump can prematurely expire a lease and flip a healthy call to indeterminate. Edge case, fail-closed.

## 4. authorized_tool_host browser/CDP paths — correct, one note

`call_browser` (`authorized_tool_host.rs:153-198`):
- Revalidates the full run authority (status Running, revision, plan_version, conversation, project, permission profile, environment id) before dispatch (`:131-151`), reserves the run-scoped once-permission *before* any await so concurrent calls cannot share it (`:161-167`), and restores the reservation only when the result is a consent short-circuit (`origin_consent_required | full_cdp_consent_required | credential_fill_consent_required`, `:177-196`) *and* the run authority is still live — a retry after the user grants consent is not double-charged.
- Browser tools deliberately bypass the digest ledger so consent short-circuit `Ok` results are not ledgered as Completed (which would trap post-consent retries behind replay) — comment and behavior at `:252-262`. Sound.
- `browser_fill_credentials` and `browser_cdp_raw` sit in the mutating tier (`:557-565`) and flow through the same consent gate.

Note (edge case, fail-closed): a *transport* failure (result `Err`) after a once-permission was reserved does not restore the once-permission — only consent-pending results do (`:191` restores solely on `consent_pending`). A flaky browser bridge burns the user's one-shot approval, forcing re-approval. Same shape as the pass-2 replay-consumption note; predictable and conservative.

## 5. AutomationEditorDialog field mapping vs cron-jobs API — mapping correct; one confirmed UX bug

Field mapping verified against `src/application/schemas/cron.py` (`CronJobCreate` `:83-113`, `CronJobUpdate` `:116-133`) and `src/domain/model/cron/value_objects.py`:
- All submitted keys exist backend-side with matching names: `name, description, enabled, delete_after_run, schedule{kind,config}, payload{kind,config}, delivery{kind,config}, conversation_mode, conversation_id, timezone, stagger_seconds, timeout_seconds, max_retries` (`AutomationEditorDialog.tsx:81-101`).
- Enum values match: schedule `cron|every|at` (`ScheduleType`, `value_objects.py:21-26`), payload `system_event|agent_turn` (`:171-175`), conversation mode `reuse|fresh` (`:290-294`).
- Config keys match the normalizers: cron `expr` (backend also accepts `expression`, `:72-77`), every `interval_seconds` (`:51-65`), at `run_at` (backend also accepts `target_time`, `:88-92`; the dialog reads both on hydrate `:391-395`), agent_turn `{message}` / system_event `{content}` (`:185-205`).
- Edit path sends `expected_revision: editorJob.revision` + stable per-revision idempotency key (`AutomationsPage.tsx:214-221`); toggle/delete likewise (`:245-256, 271-281`). Missing-conversation preservation (saved conversation outside the loaded catalog) is handled explicitly (`automationConversationModel.ts:45-53`), and submit is blocked when a reuse-mode binding is unresolvable (`AutomationEditorDialog.tsx:75, 311`).

**Confirmed bug (UX, medium): the `webhook` delivery option is a dead end.** The dialog offers `none | announce | webhook` (`AutomationEditorDialog.tsx:187-197`) but always submits `delivery: { kind, config: {} }` (`:94`) — there is no URL/headers/secret input. Backend `CronDelivery` documents webhook config as requiring `{"url": …}` (`value_objects.py:240-268`), and nothing in the backend ever consumes `DeliveryType.WEBHOOK` (or `ANNOUNCE`) at run time — the only references are schema echo/redaction (`schemas/cron.py:326-327`) and display (`cron_tool.py:102`). The web client avoids this by not surfacing delivery at all (`web/src/pages/project/CronJobs.tsx` has no delivery UI). Net effect: a desktop user can pick "webhook" (or "announce"), the job saves cleanly, and no delivery ever happens — silently. Either hide the non-`none` options or add the URL field plus backend execution.

Minor: the `at` schedule field is a free-text input with no client-side ISO-8601 validation (`AutomationEditorDialog.tsx:157-164, 387`); invalid values surface as a server 422 via the inline error slot — acceptable, but a `datetime-local` input would prevent the round-trip.

## 6. NewTaskFlow + WorkspaceOverview — correct, two minor notes

`NewTaskFlow.tsx` (1425 lines) traced across all four phases:
- State machine: define → planning → review → launching with epoch + actor guards on every async continuation (`flowEpochRef`/`activeActorIdRef` checks at `:734-746, 788-792, 826-831, 843-848, 859-875`); actor change mid-flow resets and closes (`:412-437`).
- Plan polling is abort-scoped, stall-guarded (empty-poll counter → retry offer via `shouldOfferPlanRetry`, `:581-586, 608-613`), and detects terminal planning failures from the local timeline (`:543-559`). New results reset review drafts and re-arm `planRequiresReview` (`:587-603`).
- Approval paths are idempotent: legacy mode-switch keeps a persisted recovery record and re-reads it before reuse (`:1051-1128`, rollback to `plan` mode on failure `:1116-1126`); versioned approval binds identity to planVersion id+version+profile+environment (`:1136-1148`).
- Task-session creation uses a persisted idempotency attempt with fingerprint-bound conflict recovery and an explicit "continue in existing workspace" resolution (`:748-810, 911-952`).
- No dead states found: every phase renders stage + footer + error slot; `approvalReady` correctly requires non-dirty review, ≥1 enabled step, capability, and no pending revision (`:247-258`).

Minor note: when a session-creation idempotency conflict is unresolved (no matching existing workspace) and the definition is unchanged, the define-stage footer renders *no* primary action at all (`:1338-1361` — conflict action unavailable, generate button suppressed by `taskSessionConflictIsCurrent`). The error banner explains the conflict and editing any field changes the fingerprint and restores the button, but a first-time user can read this as a dead end. Cosmetic.

`WorkspaceOverview.tsx` + wiring (`App.tsx:7116-7146`):
- All 20 props wired; every branch covered: no-project (`:129-171`), loading/error/unavailable/empty-catalog/stale-selection (`:173-263`), and the populated overview. Defaults are safe (unavailable attention collection, no-op retry/resolve handlers `:47-53, 91-100`).
- `buildWorkspaceOverviewModel` input threads members/agents/plan/sandbox/conversations from the dataset; `onOpenConversation` validates the id against the loaded workspace catalog before navigating and surfaces `myWork.sessionUnavailable` otherwise (`App.tsx:7141-7146`).

Minor note: `canResolveAutonomyAttention` is wired to the *retry* capability flag (`App.tsx:7132` — same `canRetryWorkspaceAutonomyAttention` role gate at `:4996-5000`). If the backend ever splits resolve vs retry roles, the desktop will over/under-show the resolve button. Currently harmless (backend enforces its own check), but the aliasing should be deliberate.

## Suggested follow-ups (priority order)

1. [Medium] `AutomationEditorDialog`: remove or implement the `webhook`/`announce` delivery options — today they save successfully and never deliver (area 5).
2. [Low] `automaticUpdateLoop.ts`: include the electron-updater error message in the `error`-event report; consider making progress-contract failures retryable (area 2, notes 1–2).
3. [Low] `NewTaskFlow`: render a disabled "generate" button with the conflict hint when an unresolved idempotency conflict suppresses the primary action (area 6).
4. [Low] `App.tsx:7132`: give resolve its own capability flag or add a comment that the aliasing is intentional (area 6).
5. [Info] MCP lease: document that `indeterminate` is terminal per idempotency key and callers must rotate keys on retry (area 3, note 1).
