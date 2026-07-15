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
