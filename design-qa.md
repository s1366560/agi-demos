# Desktop Model Provider Settings Design QA

## Verdict

- P0: none.
- P1: none.
- P2: none after the provider-kind, catalog-filtering, and unsupported-probe fixes.
- P3: the implementation uses live tenant/provider data, so the provider names and empty model catalog differ from the prototype's illustrative rows. This is authoritative content, not structural drift.

## Comparison setup

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
- Implementation URL: `http://127.0.0.1:5173/`
- Viewport: 1280 x 720.
- State: dark mode, authenticated, Settings -> Models -> Provider Overview.
- Source screenshot: `/tmp/memstack-goal-audit-20260715/07-prototype-model-settings-current.png`
- Implementation screenshot: `/tmp/memstack-goal-audit-20260715/08-implementation-model-settings-final.png`
- Focused source provider detail: `/tmp/memstack-goal-audit-20260715/11-prototype-provider-detail.png`
- Focused implementation provider detail: `/tmp/memstack-goal-audit-20260715/12-implementation-provider-detail.png`
- Provider wizard step 1: `/tmp/memstack-goal-audit-20260715/13-implementation-provider-wizard-step1.png`
- Provider wizard step 3: `/tmp/memstack-goal-audit-20260715/14-implementation-provider-wizard-step3.png`

The source and implementation screenshots were opened together at the same viewport before the final verdict. Modal geometry, three-column composition, header, sidebar, provider list, detail hierarchy, tabs, cards, spacing, typography, borders, and color treatment match closely.

## Primary interactions verified

- Open Settings as an independent modal window and navigate to Models.
- List only LLM providers; embedding and rerank providers no longer appear in this workspace.
- Select a provider and switch among Overview, Connection, Models, Routing, and Usage tabs.
- Edit an existing API-key provider without revealing or resending the stored secret.
- Validate an unchanged existing connection through the persisted-provider health endpoint.
- Open the add-provider wizard and choose a supported cloud or local runtime.
- Confirm unsupported Azure OpenAI, Bedrock, and Vertex types are hidden until provider-specific probes exist.
- Validate an Ollama draft against a local runtime before continuing.
- Confirm the primary discovered model is selected and cannot be deselected.
- Close the wizard without creating test data.
- Browser console errors: none.

## Comparison history

1. Initial comparison found an embedding provider in the LLM settings list, unsupported provider types exposed in the wizard, and a misleading provider-kind label.
2. The UI was changed to filter non-LLM operations, require `probe_supported`, and derive cloud/local labeling from the authentication contract.
3. Post-fix comparison shows four authoritative LLM providers, supported-only wizard choices, correct cloud/local labels, and a real validation gate before model selection.
4. Connection editing was hardened so endpoint/provider changes require a new key, while an unchanged endpoint can validate with the encrypted stored credential.
5. Final browser flow completed with zero console errors and no remaining P0/P1/P2 visual or interaction findings.

final result: passed

---

# Desktop Mission Control Design QA

## Verdict

- P0: none.
- P1: none.
- P2: none after the My Work width, copy, action, and density corrections.
- P3: the implementation renders authoritative workspace, model, permission, plan, and run data, so thread titles and counts differ from the prototype's illustrative fixtures. The prototype-only Attach control is intentionally omitted because no backend action exists for it.

## Comparison setup

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
- Implementation harness: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/qa/mission-control.html`
- Desktop source: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/src`
- Rust authority source: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/src-tauri/src`
- Python/cloud source: `/Users/tiejunsun/github/agi-demos/src`
- Viewports: `1440 × 1024` and `1100 × 800`.
- States: composer-first Home and grouped My Work inbox, authenticated dark desktop shell.
- Home 1440 comparison: `/Users/tiejunsun/github/agi-demos/artifacts/design-qa/compare-home-1440-final.png`
- Home 1100 comparison: `/Users/tiejunsun/github/agi-demos/artifacts/design-qa/compare-home-1100-final.png`
- My Work 1440 comparison: `/Users/tiejunsun/github/agi-demos/artifacts/design-qa/compare-my-work-1440-final.png`
- My Work 1100 comparison: `/Users/tiejunsun/github/agi-demos/artifacts/design-qa/compare-my-work-1100-final.png`

Each comparison places the source prototype and implementation side by side at their exact native viewport size. The native-resolution full-view evidence keeps the sidebar, typography, composer controls, cards, status icons, spacing, and copy legible, so a separate focused crop would not reveal additional visual information.

## Visual review

- Typography: heading scale, uppercase eyebrow treatment, muted metadata, and compact card labels align with the prototype hierarchy.
- Spacing and geometry: the 220px sidebar, centered 680px composer, 365px inbox cards, section rhythm, and both responsive breakpoints align without clipping or horizontal overflow.
- Colors and decoration: flat near-black surfaces, cyan active accents, governed amber/cyan/green status colors, subtle borders, and restrained radii match the prototype direction.
- Icons and image quality: vector icons remain crisp at both viewports; no stretched, blurred, or synthetic bitmap UI assets are present.
- Copy: the New thread, My Work, Inbox, mode, effort, permission, and workspace labels follow the current product contract. Model names, counts, durations, and statuses come from authoritative data rather than prototype fiction.

## Primary interactions verified

- Enter a composer prompt, switch Work/Code, select a real provider model, change reasoning effort and permission mode, and submit one atomic task-session request.
- Preserve Workspace policy permissions: non-managers can inspect policy values but cannot mutate them; manager changes carry the expected revision.
- Restore failure and old-capability states without creating a half-finished thread, and expose the upgrade notice for legacy services.
- Navigate the Workspace-grouped thread tree and open My Work cards directly into the authoritative conversation.
- Render plan replacement and approval against the current immutable version only.
- Keep the latest permission HITL above the composer and submit `allow`, `allow_always`, or `deny` without optimistic completion.
- Native Tauri acceptance launched through `make -C agi-stack run-desktop`; the app shell reported no fatal runtime state.
- Browser console warnings and errors in the final QA harness: none.

## Comparison history

1. The first My Work comparison found 1440px cards stretching beyond the prototype grid; the wide layout was capped at two 365px columns while the narrower breakpoint remains fluid.
2. The initial implementation retained search and refresh controls and used a Mission Control eyebrow that did not exist in the latest source state; those controls were removed and the authoritative My Work copy was restored.
3. My Work cards were approximately 50px taller than the source. Minimum height, internal spacing, and inter-section rhythm were tightened to the prototype's dense inbox treatment.
4. The sidebar primary action still said New task. English and Chinese labels now consistently say New thread / 新建线程.
5. Final same-input comparisons at both requested viewports show no remaining P0, P1, or P2 visual, responsive, accessibility, or interaction findings.

final result: passed

---

# Desktop Plan-first Task and Recovery Design QA

## Verdict

- P0: none.
- P1: none after the interactive select crash, transferred-checkpoint source controls, recovery-fork rollback, runtime credential invalidation, and cloud/local turn-replay races were fixed.
- P2: none after capability preflight, two-stage session activation, unknown-delivery recovery, exact plan authority, scoped approval recovery, accessibility, and localization were verified.
- P3: the approved prototype presents initial plan review as a full-screen creation step, while a recovered plan is intentionally reopened inside the conversation canvas. The hierarchy changes, but the plan version, persisted tasks, environment, permission, authority state, and primary action remain explicit.

## Comparison setup

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
- Implementation URL: `http://127.0.0.1:5173/`
- Viewport: `1280 × 720`.
- Task definition comparison: `agi-stack/apps/desktop/qa/new-task-plan-20260716/comparison-task-define.jpg`
- Agent planning comparison: `agi-stack/apps/desktop/qa/new-task-plan-20260716/comparison-task-planning.jpg`
- Source review and recovered session review comparison: `agi-stack/apps/desktop/qa/new-task-plan-20260716/comparison-source-review-session-recovery.jpg`
- Draft session review: `agi-stack/apps/desktop/qa/new-task-plan-20260716/session-plan-draft-1280.jpg`
- Read-only session review: `agi-stack/apps/desktop/qa/new-task-plan-20260716/session-plan-readonly-1280.jpg`
- Approved session review: `agi-stack/apps/desktop/qa/new-task-plan-20260716/session-plan-approved-1280.jpg`
- Runtime recovery settings: `agi-stack/apps/desktop/qa/new-task-plan-20260716/runtime-recovery-settings-1280.jpg`

The source and implementation captures were placed together at the same viewport before the final judgment. Task definition and planning preserve the source composition, typography, stepper, boundary rail, progress rhythm, cards, controls, and dark desktop treatment. The session recovery view keeps the established conversation canvas instead of introducing a second full-screen shell.

## Primary interactions verified

- Probe Agent Plan capability before creating a workspace, conversation, task list, or other server artifact; unsupported Python/cloud runtimes fail with localized guidance and a direct Settings recovery action.
- Apply Rust-local and Python-cloud runtime presets as atomic URL-and-mode identities; crossing that identity boundary clears the in-memory Bearer and native trusted session before reconnecting.
- Reject opaque or non-HTTP(S) runtime identities, and clear both the cloud API key and local launch token whenever the validated origin or runtime mode changes.
- Persist a new task in the workspace catalog first, bind its workspace and Agent plan mode, deliver the Agent turn, and activate the session only after the dispatch path is established.
- Register the WebSocket acknowledgement before sending. Timeout or disconnect is treated as an unknown outcome, reuses the stable planning message ID, and polls authority instead of blindly creating a duplicate turn.
- Persist only an opaque, SHA-256-scoped approval recovery record with exact runtime, tenant, project, conversation, plan, message, schema, and 24-hour expiry authority; task content and credentials never enter local storage.
- Bind a cloud WebSocket `message_id` to one canonical execution payload in a durable ledger. Conflicting reuse fails closed, concurrent accepts receive one execution claim, and a committed `STARTED` turn replays its authoritative acknowledgement without creating another task.
- Commit the cloud ledger transition and first user event in one database transaction. A setup failure rolls the claim back to retryable `ACCEPTED`; a `STARTED` row without its durable user event requires manual reconciliation instead of guessing.
- Bind each Rust-local HTTP fallback message to a durable `(conversation_id, message_id, payload_hash)` record before spawning. Exact sequential or concurrent replay returns the persisted admission without another Agent execution; conflicting reuse returns `MESSAGE_ID_CONFLICT`, and the same message ID remains isolated across conversations.
- Editing the task definition, workspace, or task kind invalidates the prior planning session and prevents approval of its stale plan.
- Recover cloud `agent_task_list` state after refresh or backgrounding as readable evidence, then recheck the exact task-list signature before opening guarded review.
- Approve only the exact persisted plan ID and version with the selected execution environment and permission profile in one idempotent authority request.
- Render draft, authority-read-only, and approved states distinctly. Read-only disables approval; approved removes the approval action while keeping the plan visible.
- Change execution environment and permission selectors without losing the canvas. The browser-discovered synthetic-event lifetime crash is covered by a regression test.
- Keep the conversation plan canvas scoped to its exact session projection or recovered task list; it never substitutes the workspace envelope `dataset.plan`.
- Recover queued and running Rust runs after process restart without replaying work. Startup, terminalization, queued-input settlement, current-fork selection, and checkpoint quarantine fail closed.
- Bind every checkpoint to run, plan, project, permission, environment, and generation lineage; a recovery fork transfers that authority explicitly.
- Reject pause, resume, cancel, HITL response, review changes, and artifact-review resume before any core checkpoint side effect when the requested run is not the persisted checkpoint owner. An old source run cannot cancel or reopen its fork's checkpoint.
- Reject a new recovery-fork key from a transferred source before claim, Git worktree preparation, run insertion, decision insertion, or timeline emission. Transfer or resume failures restore source authority and remove the created branch, worktree, run, decision, and event.
- Hold one exclusive owner for the desktop SQLite store so a second process cannot concurrently recover the same runs.
- Support keyboard navigation across the session canvas tabs, focus the newly available plan, restore focus after step editing, expose live planning progress, and keep command palette and recovery copy localized.

## Verification

- Desktop frontend tests: `308 passed`.
- Production TypeScript and Vite build: passed; only the existing large-chunk advisory remains.
- Rust formatting: passed.
- Rust check and Clippy with warnings denied: passed.
- Desktop Rust runtime tests: `126 passed`.
- Python client-turn ledger, WebSocket acknowledgement, AgentService, preferred-language, use-case, and integration regressions: `39 passed`; the combined core suite was independently rerun with `37 passed`.
- Targeted Ruff, Pyright, and gettext-literal checks: passed. Targeted Mypy was terminated by the local OS with exit `137` before emitting diagnostics; Pyright reported zero errors over the changed surface.
- Alembic, using the current `.env` `DATABASE_URL`: `upgrade head`, `heads`, and `current` passed at `f9d99e5695ec (head)`.
- Browser page identity, meaningful DOM, framework-overlay absence, default selection state, selector interaction, read-only state, approved state, and screenshot evidence: passed.
- Browser console: no new error-level entries after the selector fix across the final draft, interaction, read-only, approved, login, and recovery-state navigation.
- `git diff --check`: passed.

## Comparison and hardening history

1. Same-canvas comparison confirmed the task-description and planning screens closely match the approved prototype.
2. Capability review moved plan support detection before every creating mutation and added an actionable Settings recovery path.
3. Delivery review split catalog persistence from active-session adoption and made ambiguous WebSocket outcomes idempotently recoverable.
4. Authority review removed the workspace-plan fallback and made draft approval depend on the exact persisted conversation plan version.
5. Rendered interaction QA found a select-change crash that static rendering did not expose; both selectors now capture values before functional state updates.
6. Crash-recovery review added checkpoint lineage, transaction-safe input settlement, fail-closed terminalization, current-fork recovery, and exclusive store ownership.
7. Final adversarial review found that an old recovery source could still address a transferred fork checkpoint. All core checkpoint controls now verify exact run authority while holding the conversation claim, and dedicated cancel/resume regression tests prove the fork remains unchanged.
8. Runtime review found that a malformed or cross-origin transition could retain credentials. Runtime identity is now HTTP(S)-only and clears both cloud and native credentials whenever origin or mode changes.
9. Unknown approval delivery gained an opaque, versioned, runtime-scoped recovery record with an exact plan signature, stable message ID, and bounded expiry; accepted attempts cannot be replayed blindly.
10. Accessibility review added the complete tab keyboard contract, plan announcements and focus handoff, editor focus restoration, busy/live states, and localized recovery and command copy.
11. Cloud replay review added a durable client-turn ledger, payload conflict detection, a single transactional execution claim, and stable event identity so the same WebSocket turn cannot create a second agent task.
12. Recovery-fork review moved source authority validation ahead of every side effect and added checked rollback across branch, worktree, run, decision, event, and source authority, including a real Git worktree regression.
13. Final protocol review found the local HTTP fallback could still repeat a completed message after a lost response. A schema-versioned SQLite client-turn ledger now admits the message once, rejects payload conflicts, survives reopen, and is covered by lost-response, concurrent-replay, invalid-ID, and cross-conversation tests.

The desktop run database, core checkpoint database, and Git worktree cannot participate in one physical transaction. Explicit failures now roll back every created resource and restore exact authority, while a rollback I/O failure is surfaced with its still-associated recovery resources. A process crash in the narrow database-commit/worktree-cleanup window can still leave a worktree that requires manual cleanup.

The cloud ledger's `ACCEPTED -> STARTED` transition and first user event are atomic, and replay of a committed turn never spawns a second task. The later actor handoff is not physically exactly-once: a crash after the user event commit can require manual reconciliation, while a `STARTED` row without that event is rejected explicitly. These are documented durability boundaries, not silent duplicate-execution paths.

The Rust-local client-turn admission is committed before its Tokio task is spawned, so replay is at-most-once across response loss and process reopen. A process crash in that narrow admission-to-spawn window can require manual reconciliation, but it cannot silently execute the same message twice.

final result: passed

---

# Desktop Workspace Hierarchy Design QA

## Verdict

- P0: none.
- P1: none after the context-switch recovery, workspace-session lazy loading, and lifecycle/run-status contract fixes.
- P2: none after governed statuses were localized, live expansion was preserved across refresh completion, node failures gained accessible retries with explicit focus handoff, and refresh/lazy-load races gained latest-request authority.
- P3: the implementation uses the live Default Tenant project, whose selected workspace has no active conversations. Empty metrics and rows are authoritative content, not structural drift from the prototype's illustrative data. The cloud API also does not yet expose a stable latest-run summary on conversation rows, so cloud lifecycle-only sessions remain neutral while My Work stays the attention authority; the client does not fabricate run identity or status.

## Comparison setup

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
- Implementation URL: `http://127.0.0.1:5173/`
- CSS viewport and capture: `1325 × 964`.
- State: Simplified Chinese, authenticated, tenant and project selected.
- Workspace source: `agi-stack/apps/desktop/qa/hierarchy-source-workspace-1325.png`
- Workspace implementation: `agi-stack/apps/desktop/qa/hierarchy-implementation-workspace-final-1325.png`
- Workspace same-canvas comparison: `agi-stack/apps/desktop/qa/hierarchy-workspace-final-comparison-1325.png`
- Settings source: `agi-stack/apps/desktop/qa/hierarchy-source-settings-workspace-1325.png`
- Settings implementation: `agi-stack/apps/desktop/qa/hierarchy-implementation-settings-after-1325.png`
- Settings same-canvas comparison: `agi-stack/apps/desktop/qa/hierarchy-settings-comparison-1325.png`
- Conversation source: `agi-stack/apps/desktop/qa/hierarchy-source-conversation-1325.png`
- Conversation implementation reference: `agi-stack/apps/desktop/qa/session-detail-reference-1325.png`
- Conversation same-canvas comparison: `agi-stack/apps/desktop/qa/hierarchy-conversation-comparison-1325.png`

The source and implementation captures were placed together before the final judgment. Sidebar width, navigation rhythm, Workspace → Conversation nesting, overview grid, independent Settings shell, conversation header, narrative thread, persistent composer, and work canvas align with the approved prototype.

## Primary interactions verified

- Sign in and hydrate the authoritative tenant, project, and selected workspace.
- Expand only the selected workspace on first load while preserving manual expansion state.
- Expand a second workspace and load its conversations on demand; other collapsed workspaces remain explicitly deferred.
- Complete an in-flight workspace conversation load after navigating to another workspace in the same project, while rejecting responses after any identity, tenant, project, endpoint, or credential boundary changes.
- Allow only the latest global refresh and latest request for each workspace to settle; a newer refresh takes ownership of unresolved refresh nodes so even an early failure cannot leave an orphaned loading state.
- Merge all dataset commits from React's current state instead of replacing it from a passive ref snapshot, and retain any newer authoritative run revision already delivered by the live socket when a list response arrives.
- Keep a workspace's already loaded session state visible across refreshes and commit the latest user expansion state after pending hydration settles.
- Announce loading, empty, and error transitions with polite live regions; project and workspace errors expose explicit keyboard-focusable retry actions.
- Move focus from a retry action to the owning navigation or workspace disclosure before the conditional error state unmounts.
- Move the global workspace-recovery action's focus to the stable workbench before its alert unmounts.
- Preserve the approved tree geometry with native navigation, button, and link semantics instead of claiming an incomplete ARIA tree keyboard contract.
- Escalate workspace root status only from structured latest-run attention or failure states, never from the conversation lifecycle `active` value; root labels use order-independent aggregate states while session rows keep the exact reason.
- Translate active, running, queued, paused, input, approval, review, completed, failure, disconnected, interrupted, cancelled, archived, inactive, and unknown statuses without exposing raw protocol values; approval and input remain distinct.
- Open Settings as an independent modal and navigate to the Tenant → Project selector.
- Treat authoritative context switching and subsequent runtime hydration as separate outcomes; a successful switch closes Settings and a failed hydration exposes one workspace reload action.
- Keep conversation detail thread-first and leave the work canvas on demand.
- Browser console error-level entries: none.
- Desktop automated tests: 268 passed.
- Desktop Rust runtime tests: 91 passed; conversation lifecycle remains `active` while `metadata.run` carries the authoritative latest-run identity and status.
- Rust formatting and Clippy with warnings denied: passed.
- Production TypeScript and Vite build: passed; only the existing large-chunk advisory remains.

## Comparison history

1. Initial audit found all workspaces eagerly hydrating every active conversation, partial-success context switches trapped inside Settings, root status dots ignoring child attention, and several raw status enums.
2. The tree model gained explicit deferred/loading/error/empty/ready availability and governed status presentation.
3. Runtime refresh now hydrates only selected or expanded workspace roots, while node expansion performs a scoped, load-once request guarded by context revision and project authority.
4. The context switch now commits the authoritative selection independently from workspace hydration and exposes a retry action in the main surface.
5. Same-canvas QA found and fixed two final presentation issues: deferred roots no longer claim zero sessions, and `inactive` is rendered as localized “离线” instead of a raw green status.
6. Contract review then separated conversation lifecycle from execution state, reconciled the expansion set at commit time, and added live-region retry states without changing the approved geometry.
7. Pre-commit review removed the workspace-selection race from lazy hydration, separated approval from generic input, and replaced false ARIA tree roles with native navigation semantics.
8. Independent concurrency review then added global and per-workspace request generations, functional state merges, retry focus handoff, order-independent root attention labels, and preservation of conversation lifecycle during run socket updates.
9. Final race review added refresh-request takeover and monotonic run-authority merging, preventing early refresh failures or stale list responses from regressing the tree.
10. Final workspace, Settings, and conversation comparisons have no actionable P0/P1/P2 visual or interaction findings.

final result: passed
