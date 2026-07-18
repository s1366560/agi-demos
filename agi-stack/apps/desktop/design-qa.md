# Login screen design QA

## Comparison target

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/login-screen.png`
- Compact source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/login-screen-1100.png`
- Implementation screenshot: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/qa/login-screen-1440-final.png`
- Compact implementation screenshot: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/qa/login-screen-1100-final.png`
- Viewports: `1440 × 1024` and `1100 × 800`, device scale factor `1`
- State: Simplified Chinese, signed out, work email populated with `alex@northstar.ai`, email focused, password hidden, keep-signed-in selected
- Render method: the running Vite application was captured from headless Google Chrome through the Chrome DevTools Protocol because the in-app Browser surface was unavailable to this Codex session.

## Full-view comparison evidence

The source and implementation were normalized to the same viewport and placed in one horizontal comparison image for each viewport before review. Both comparisons preserve the same split-screen proportions, content state, crop, and theme.

- The vertical split lands at the same position at both native sizes.
- Brand, story, proof rows, sign-in form, and bottom access help preserve the source hierarchy and order.
- Neither native viewport has horizontal overflow, clipped content, or accidental wrapping.
- The 1100-pixel layout retains the two-column desktop composition shown by the compact source.

## Focused-region comparison evidence

Focused horizontal comparisons were also reviewed for the sign-in form and the lower story/proof region at `1440 × 1024`.

- Form control widths, 7-pixel radii, borders, divider, labels, checkbox, password affordance, and arrow alignment match the source.
- The headline uses the same three-line wrap, scale, weight, tracking, and line height.
- Proof rows use the same 32-pixel icon track, 58-pixel minimum height, 7-pixel gap, border treatment, and copy hierarchy.
- The supplied 192-pixel MemStack image is used for both brand placements; it is byte-identical to the prototype asset.

## Required fidelity surfaces

- Fonts and typography: Inter/system fallbacks, explicit control sizes, heading scale, tracking, and wrapping match. Radix's inherited line height was neutralized on the login surface so unqualified headings and labels follow the prototype's normal line height.
- Spacing and layout rhythm: the source grid, 430-pixel form, 48-pixel form-side padding, story gutters, card gaps, divider spacing, and bottom help placement are reproduced at both viewports.
- Colors and visual tokens: dark surfaces, borders, focus treatment, semantic error state, and the muted teal primary action match the visible source. No gradient or invented elevation was added.
- Image quality and asset fidelity: the original MemStack raster asset is used at 38 and 22 pixels with the source radii. There are no CSS-art or placeholder replacements.
- Copy and content: the Chinese source copy is present verbatim and in the same order. The above-the-fold copy diff has no added, removed, renamed, or reordered visible strings.
- Icons: the same Radix icon family and source metaphors are retained for task kernel, review, isolation, password visibility, selection, lock, and arrows.
- Responsiveness: `1440 × 1024` and `1100 × 800` pass without overflow. The existing under-900-pixel single-column fallback remains available outside the source's desktop range.
- Accessibility: form labels remain semantic, the logo has useful alt text, the decorative SSO logo has empty alt text, password visibility has a localized accessible name, required fields use native validation, and keyboard focus remains visible.

## Interaction verification

- Email focus and controlled input update: passed.
- Keep-signed-in toggle off and on: passed.
- Password reveal and conceal: passed.
- Workspace SSO in an unconfigured cloud runtime: passed with an explicit localized error; it never falls through to password login.
- Email submit remains connected to the existing authenticated API flow.
- Browser console and runtime exceptions: none.
- Automated desktop tests: 111 passed.

## Comparison history

### Iteration 1 — blocked

- [P1] The implementation conditionally showed either local SSO or email login, while the source shows both in one form.
- [P1] The source's SSO row, email divider, remember option, forgot-password action, and workspace-access help were missing.
- [P1] Story and proof copy differed from the approved source.
- [P2] A CSS letter tile replaced the real MemStack image.
- [P2] Radix's inherited line height pushed the form rhythm below the source.
- [P2] The primary action used a noticeably more saturated cyan than the source capture.

Fixes: rebuilt the component from the source information architecture; restored the original image and exact bilingual copy; kept both authentication paths visible; added the missing controls; isolated SSO routing; reset login-surface line height; and matched the visible primary-action color.

### Iteration 2 — passed

Post-fix full-view and focused comparisons at both native sizes show no actionable P0, P1, or P2 differences. The only residual variation is the expected softness of the JPEG-encoded source files compared with the lossless PNG implementation captures.

## Findings

- Credential persistence P0: resolved in Iteration 5.
- [P1] Real outbound connection probing and automatic model discovery remain unimplemented.
- [P1] The full Provider/authentication matrix and advanced connection fields remain incomplete.
- [P1] Routing is still tenant-scoped instead of the researched workspace policy scope; Fast and
  Vision workloads remain unavailable.
- [P1] Usage statistics and Provider mutation audit events still lack authoritative runtime data.

## Intentional product constraints

- Production starts with an empty email field rather than seeding a fictional account. The QA capture populated the source's example email to compare the same visual state.
- The prototype simulates SSO success. Production uses the native trusted local session only when that runtime is ready and otherwise fails closed with a localized message.
- Forgot-password and access-request controls remain visual-only, matching the source prototype, until dedicated product routes are specified.

## Follow-up polish

- [P3] None required for this approved desktop range.

final result: passed

---

# Tenant model-routing policy design QA

Date: 2026-07-18

Scope: Settings -> Models -> OpenAI -> Routing, executable workload-role assignment, ordered
fallback editing, timeout failover, save/conflict feedback, local-runtime compatibility, and tenant
scope.

## Visual truth and implementation evidence

- Source visual truth:
  `agi-stack/apps/desktop/qa/routing-policy-source-final.png`
- Implementation screenshot:
  `agi-stack/apps/desktop/qa/routing-policy-implementation-final.png`
- Focused source region:
  `agi-stack/apps/desktop/qa/routing-policy-source-focused.png`
- Focused implementation region:
  `agi-stack/apps/desktop/qa/routing-policy-implementation-focused.png`
- Viewport: browser content reports `1325 x 939`, device scale factor `1`; both in-app Browser
  captures use the same `1325 x 745` visible page region after browser chrome.
- State: Simplified Chinese, dark theme, Settings modal, Models selected, OpenAI selected, Routing
  tab selected. The implementation uses the local QA authority with OpenAI, Anthropic, and an
  OpenAI-compatible local gateway.

## Full-view comparison evidence

The source and implementation screenshots were opened together in one comparison input. The
settings frame, 183-pixel section rail, 292-pixel provider list, provider detail column, header,
five-tab strip, two-column role grid, fallback card, dark palette, border density, and vertical
rhythm align at the same visible crop. No persistent control is hidden by viewport overflow.

The implementation intentionally shows three locally executable provider types instead of the
source's five-provider cloud catalog. It labels the authority as tenant routing because the SQLite
policy is tenant-scoped and shared by that tenant's projects and workspaces. Fast and Vision remain
visible in the four-role contract but are disabled with an explicit local-runtime limitation;
Default and Coding are the two roles with structured production callers. These are truthful product
constraints, not accidental layout drift.

## Focused-region comparison evidence

The provider header, tabs, role card, four selectors, fallback card, and first ordered fallback
were cropped from the actual source and implementation screenshots and opened together. The
following surfaces remain readable at native scale:

- provider icon, title, connection status, endpoint summary, and tab alignment;
- workload eyebrow, heading, explanatory copy, and save action;
- two-by-two role geometry, labels, helper copy, select height, radii, and borders;
- fallback order numbering, select geometry, and row controls.

The implementation adds explicit up/down/remove controls, disables Save until the policy is dirty,
and marks Fast/Vision as unavailable. Those differences expose real ordered mutation, prevent no-op
writes, and avoid claiming runtime capabilities that do not yet exist; they do not alter the
approved composition.

## Required fidelity surfaces

- Fonts and typography: the existing desktop sans-serif stack, heading weights, compact eyebrow,
  tab labels, helper copy, and exact model IDs preserve the source hierarchy and wrapping.
- Spacing and layout rhythm: frame margins, three-column settings layout, provider header height,
  tab rhythm, two-column role grid, card padding, fallback rows, and radii match the source. The
  shorter provider list is an intentional local-runtime data difference.
- Colors and visual tokens: flat near-black surfaces, slate borders, muted labels, green
  configuration-valid state, amber reserved-role limits, and cyan selection/action tokens remain
  consistent. No gradient or invented elevation was introduced.
- Image quality and asset fidelity: the existing MemStack and provider raster/icon assets are
  retained; no visible source asset was replaced with CSS art, text glyphs, or placeholder boxes.
- Copy and content: role names, descriptions, fallback rationale, provider context, and model IDs
  are localized. `Tenant routing` replaces the source's `Workspace routing` so the UI states the
  actual persistence boundary. Local validation says `Configured` and never fabricates an external
  connectivity probe.
- Accessibility: the provider tabs use the tab pattern; role and fallback selectors have semantic
  labels; fallback move/remove actions have localized accessible names; errors use alerts and save
  confirmation uses a status region.

## Interaction verification

- Changed the Coding route from Anthropic to OpenAI: passed; Save became available.
- Fast and Vision selectors: passed; both are visibly disabled and explain that the current local
  runtime cannot execute them.
- Added a third fallback, moved it upward, and removed it again: passed; duplicate choices stayed
  disabled and row numbering/actions updated.
- Saved the policy: passed; the dirty state reset, Save became disabled, and the localized
  `Tenant routing policy saved` status appeared.
- Candidate authority: passed; only providers projected by the local API as
  `configuration_valid` are selectable. Persisted unavailable targets remain visible but disabled.
- Failover execution: passed in Rust tests; each candidate has a 45-second bound, timeout advances
  to the next target, and a single candidate is also bounded.
- Conflict recovery: passed in source and automated contract tests; a 409 reloads both provider
  roster and policy, then refreshes the runtime projection under the original scope guard.
- Legacy runtime selection: passed in Rust and client tests; mutation requires both the provider
  revision and routing-policy revision, so it cannot overwrite a newer policy silently.
- All-candidates-unavailable state: passed in component contract tests; the warning supplements the
  persisted role/fallback editor instead of hiding authoritative targets.
- Current-page console: no warning or error entries after the final QA navigation and interaction;
  only Vite connection and React development information was emitted.

## Comparison history

### Iteration 1 — blocked

- [P1] `routing-policy-implementation-before.png` exposed only the Default role; Fast, Coding, and
  Vision were disabled and the fallback list was not editable.
- [P1] The Rust runtime persisted only a selected default provider and did not consume ordered
  fallbacks during execution.
- [P2] Every provider/model appeared selectable even when the local runtime could not execute it.
- [P2] Member read access, optimistic-conflict recovery, authoritative null roles, and runtime
  projection refresh were inconsistent with the visible UI contract.

Fixes: added the authoritative tenant policy API and revision contract; implemented the executable
Default/Coding assignments, ordered fallback editing, disabled unavailable targets, conflict
reload, read-only member access, structured Work/Code routing, and sequential execution failover.
Provider mutation and policy mutation now share one runtime/store lock order.

### Iteration 2 — runtime-truth audit

- [P1] Fast/Vision were editable despite having no structured production caller.
- [P1] A pending provider could block forever before reaching fallback.
- [P2] Conflict recovery omitted the provider roster and runtime projection.
- [P2] Frontend candidate readiness diverged from the Rust runtime projection.
- [P2] Stale fallback rows could incorrectly disable Add fallback.
- [P2] The QA mock fabricated `healthy`, latency, and an external probe.
- [P2] The legacy runtime-selection endpoint could rewrite a newer policy using only provider
  revision authority.
- [P2] The no-available-candidate warning replaced the editor and hid persisted targets.

Fixes: Fast/Vision are rejected by local policy mutation and disabled with explicit copy; all LLM
candidates use bounded timeout failover; 409 recovery reloads roster and policy; candidate options
require server-projected `configuration_valid`; fallback availability is set-based; QA mirrors the
local configuration-only response with `probed: false`.
Legacy selection now requires both optimistic revisions, and an unavailable-candidate warning no
longer suppresses the authoritative editor.

### Iteration 3 — passed

The post-fix full-view and focused comparisons show no actionable P0, P1, or P2 visual findings.
The remaining differences are the explicit tenant scope, locally supported provider roster, exact
runtime model IDs, disabled reserved roles, dirty-save state, and usable reorder controls described
above.

## Findings

No actionable P0, P1, or P2 findings remain.

## Follow-up polish

- [P3] A future structured metadata-generation contract can activate Fast. A separate attachment
  contract plus multimodal adapters can activate Vision. Until then, the current conversation
  contract explicitly routes Work to Default and Code to Coding without guessing intent from text.

final result: passed

---

# Long-session history recovery design QA

Date: 2026-07-18

Scope: bounded conversation history, backward cursor pagination, failure recovery, manual reading
position, and live-tail following.

## Visual sources

- Prototype at `1375 x 939`:
  `agi-stack/apps/desktop/qa/session-history-source-1375x939.png`
- Current production-component capture at `1375 x 939`:
  `agi-stack/apps/desktop/qa/session-history-implementation-1375x939.png`
- Exact same-viewport full comparison:
  `agi-stack/apps/desktop/qa/session-history-comparison-1375x939.jpg`
- Focused conversation-region comparison:
  `agi-stack/apps/desktop/qa/session-history-focused-comparison.jpg`
- Pagination control state:
  `agi-stack/apps/desktop/qa/session-history-pagination-control-1375x939.png`
- Recoverable failure state:
  `agi-stack/apps/desktop/qa/session-history-error-retry-1375x939.png`

The default implementation capture keeps the approved session narrative unchanged. The two
conditional captures use the production `ChatPanel` inside its deterministic session QA host so the
new controls can be reviewed without fabricating native runtime data. The focused conversation
comparison is the visual authority for this iteration; the wider comparison is supporting evidence
for density and theme rather than a new full-shell fidelity claim.

## Same-viewport review

- Both source and implementation were measured at `1375 x 939`, device scale factor `1`.
- Both documents report `scrollWidth = clientWidth = 1375` and `scrollHeight = clientHeight = 939`;
  no page-level overflow hides controls.
- The existing flat dark-slate surface, cyan activity treatment, compact metadata, message-card
  hierarchy, and fixed composer remain unchanged in the default state.
- `Load earlier` is a quiet text action above the narrative and does not compete with the current
  activity card or composer.
- A failed earlier page remains inline with the retained conversation window, uses alert semantics,
  and exposes one explicit retry action. It does not replace the session with a generic empty state.
- The `Jump to latest` action is conditional and overlays the lower narrative edge only after a
  reader has moved away from the live tail; it is absent while the view is pinned.

## Interaction and accessibility verification

- The pagination QA state exposed `加载更早记录`; activating it prepended the earlier event and
  removed the exhausted control.
- The failure QA state retained every loaded message, announced the error through an alert, and
  exposed `重试加载更早记录`; activating retry loaded the earlier event and cleared the alert.
- The scroll viewport exposes the localized `会话记录` accessible name, `aria-busy`, and keyboard
  focus. Loading, retry, and jump actions use native buttons.
- Automatic backward pagination stops after a missing, repeated, or non-monotonic cursor. Manual
  retry remains available and does not discard the current page.
- Prepending history restores the previous DOM anchor by conversation and stable member identity.
  The clean concurrent-tail scenario preserved the pre-load anchor within `0.125` CSS pixels while
  one live event arrived before the earlier page; both events remained visible after settlement.
- New live events follow only while the reader is pinned near the bottom; changing sessions still
  opens at the latest event. Expanded tool/activity groups retain their disclosure state when a
  page merge changes the rendered group boundary.
- Browser warning/error log in a fresh tab after the concurrent-tail and prepend flow: empty.

## Findings resolved

- P0: none.
- P1: local Rust previously returned an unbounded timeline and ignored cursor query parameters.
  It now validates the exact project scope, bounds `limit`, applies exclusive tuple cursors, returns
  oldest-first pages, supports the bounded `from + before` range, and computes `has_more` from rows
  that actually precede the page. Legacy rows without counters receive position-backed cursors;
  explicit duplicate cursor tuples fail closed instead of silently skipping an event.
- P1: the React client could silently accept repeated or non-monotonic pages. Pagination now fails
  closed unless the item window grows and the first cursor moves strictly backward.
- P1: prepend, refresh, and live append updates previously shared one unconditional scroll-to-bottom
  behavior. The scroll model now distinguishes replacement, prepend, append, and stable updates.
- P2: history failures previously had no targeted recovery path. The retained window now has a
  localized retry action, while a full initial-load failure continues to refresh the whole session.
- P2: keyboard readers now receive a named, busy-state-aware scroll region and native actions for
  earlier history, retry, and the live tail.
- P2: DOM height-delta anchoring could include a concurrent tail append and cross conversation
  boundaries. Restoration now uses a conversation-scoped visible anchor, stable group identity,
  member-lineage fallback, and a post-layout correction.

## Verification

- Desktop tests: 377 passed.
- Desktop TypeScript and production build: passed; the existing large-chunk advisory remains P3.
- Rust library tests: 156 passed.
- Rust formatting and Clippy with warnings denied: passed.
- Same-viewport browser QA: no page overflow and no warning/error console entries.

No actionable P0, P1, or P2 finding remains in this iteration's history-recovery scope.

final result: passed

---

# Local workspace-to-session continuity design QA

Date: 2026-07-17

Scope: native local login, Settings tenant/project switch, workspace-to-session tree,
conversation selection, persisted narrative content, and the current-activity summary.

## Visual sources

- Prototype initial conversation state:
  `agi-stack/apps/desktop/qa/session-detail-source-1375x939.png`
- Post-fix production-component capture:
  `agi-stack/apps/desktop/qa/session-activity-structured-1375x939.png`
- Exact `1375 x 939` prototype/focused comparison:
  `agi-stack/apps/desktop/qa/session-detail-structured-comparison-1375x939.jpg`

## Interaction evidence

The rebuilt debug `.app` was exercised through the native UI. The verified route was:

1. Continue with local workspace.
2. Open Settings -> Workspace.
3. Select Northstar Labs -> Desktop Client and apply the context switch.
4. Confirm the two-workspace tree and three Desktop Client sessions.
5. Open `Fix flaky data-pipeline test`.

The selected session rendered the persisted user request, Agent plan, isolated-worktree event,
four tool calls, root-cause message, and verification update. The real workspace name is projected
as `Desktop Client`; no generic `Local workspace` label is substituted.

## Same-viewport comparison

The focused production-component capture and prototype were placed together at the exact
`1375 x 939` viewport before final judgment. The current-activity card preserves the source's
hierarchy while making the authority boundary explicit:

- `Verifying the isolated fix`
- `Patch applied`
- `Live` only in the QA fixture's explicit running/connected state
- `Agent reported · 18 tests · 50 race runs` for free-form verification copy

The browser-reported viewport and document dimensions are both `1375 x 939`; horizontal overflow
is false and the warning/error console is empty. The combined input was used to judge sidebar,
conversation column, context rail, composer, message cards, and collapsed activity groups.

## Findings resolved

- P0: the native demo conversation previously opened with an empty timeline. A transactional,
  idempotent Rust seed now persists 13 stable narrative events. Seed/event conflicts fail closed,
  while an existing unrelated user timeline is never overwritten.
- P1: selecting another conversation in the same tenant/project/workspace no longer reconnects the
  whole runtime or tears down its live channel. Cross-workspace selection still performs the full
  authority refresh.
- P1: timeline requests use the target request configuration, so a selection cannot read through a
  stale workspace scope during a context transition.
- P1: initial and paginated timeline requests now validate both request generation and scope epoch;
  resets invalidate outstanding requests before clearing visible state.
- P1: conversation projection resolves the persisted workspace name instead of fabricating a
  generic local label.
- P2: the activity summary distinguishes validated projection counts from free-form event copy.
  Only a running authoritative run with connected updates is labeled `Live`; event-owned evidence
  is explicitly labeled `Agent reported`.

## Intentional authority boundary

The prototype capture includes an actively executing run with stage progression, elapsed time, and
worktree authority. The local seed does not fabricate a live run. Until a real run exists, the
native inspector truthfully shows unavailable run state and plan mode, while the conversation card
uses `Latest activity` / `Recorded` and keeps Agent-reported evidence inspectable. This is an
intentional runtime boundary, not a visual fallback.

## Verification

- Desktop tests: 366 passed.
- Desktop TypeScript and production build: passed.
- Rust library tests: 151 passed.
- Rust formatting and Clippy with warnings denied: passed.
- Native debug bundle: built and exercised through login -> settings -> hierarchy -> session.
- Focused Browser QA: exact live/Agent-reported checkpoint state, no overflow, no console
  warnings/errors.

final result: passed

---

# Workspace hierarchy and overview design QA

Date: 2026-07-17

Scope: workspace-to-conversation tree, workspace overview geometry, structured status presentation,
and the native local hierarchy used to exercise the prototype's happy path.

## Comparison target

- Source: `agi-stack/apps/desktop/qa/hierarchy-workspace-authority-source-1565.png`
- Implementation: `agi-stack/apps/desktop/qa/hierarchy-workspace-authority-implementation-1565.png`
- Readability source: `agi-stack/apps/desktop/qa/hierarchy-workspace-authority-source-readable-1280.png`
- Readability implementation:
  `agi-stack/apps/desktop/qa/hierarchy-workspace-authority-implementation-readable-1280.png`
- Viewports: `1565 x 1161` for the authority comparison and `1280 x 720` for the final
  prototype/fixture readability comparison, device scale factor `1`
- Source state: Northstar / Desktop Client with two workspaces and four conversations.
- Implementation state: authenticated cloud workspace overview with authoritative tenant, project,
  workspace, sandbox, memory, and member data.

## Full-view and focused-region comparison

The reference and implementation were inspected together at the same viewport. The implementation
now uses the prototype-owned canvas origin (`x = 284`, `y = 34`), matching the source header and card
anchors after removing the legacy eight-pixel pane inset. Summary, metric, system, and recent-session
regions follow the source proportions and typography. The sidebar preserves the workspace-to-session
tree while keeping status separate from descriptive copy.

Content values differ deliberately: the implementation capture is connected to the current cloud
authority, while the source capture contains prototype sample data. The native local runtime now
seeds the Northstar / Desktop Client hierarchy transactionally so that the same happy path can be
exercised without fabricating cloud state or run history.

The final `1280 x 720` comparison uses the live prototype and the implementation's deterministic
workspace QA fixture. Both surfaces were updated in lockstep to a 10-pixel minimum leaf-text size and
the higher-contrast muted token. Browser-computed text never falls below 10 pixels, neither surface
overflows horizontally, and the enlarged captions remain inside the approved card geometry. After
normalizing the inherited Radix font metrics and QA sidebar width, header, summary, metric, system,
and lower-grid anchors, widths, and heights match the live prototype at the subpixel level.

## Findings resolved

- P0: added a stable, idempotent Rust local hierarchy seed for two workspaces and four scoped
  conversations; immutable scope conflicts fail closed and user-edited titles, modes, and timestamps
  are preserved across reopen.
- P1: seeded conversation workspace reassignment now fails at the mutation boundary, preventing a
  valid PATCH from making the local runtime unstartable on its next launch.
- P2: seed validation checks both serialized conversation scope and the SQLite project/workspace
  columns so column/JSON divergence cannot hide sessions from scoped lists.
- P1: aligned the workspace overview origin, width, grid proportions, card heights, spacing, and
  typography with the source capture.
- P1: replaced inherited 6.5–9 pixel low-contrast captions in both the design prototype and Desktop
  implementation with readable 10–11 pixel captions while preserving the shared geometry.
- P1: reduced workspace secondary copy to authoritative conversation counts or load state; status is
  exposed through an accessible labeled dot.
- P1: removed API connection inference from the environment card. Sandbox presentation now maps only
  explicit structured sandbox status, covers the complete server/local lifecycle vocabulary, and
  keeps missing status visibly unknown.
- P2: conversation rows prefer structured display, environment, and progress metadata and never infer
  semantics from conversation titles.

## Verification

- Desktop tests: 356 passed.
- Desktop TypeScript and production build: passed.
- Rust library tests: 148 passed.
- Rust formatting: passed.
- Final comparison: no actionable P0, P1, or P2 visual findings remain in the compared structural
  state.

final result: passed

---

# Provider settings design QA

## Comparison target

- Popup shell source: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/settings-popup-models-1100.png`
- Provider overview source: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/model-provider-overview-final.png`
- Connection source: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/model-provider-connection.png`
- Wizard source: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/model-provider-add-wizard.png`
- Compact routing source: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/model-provider-routing-1100.png`
- Production overview captures: `qa/provider-settings-overview-1440.png` and `qa/provider-settings-overview-1100.png`
- Same-canvas compact comparison: `qa/provider-settings-comparison-1100.jpg`
- Interaction captures: `qa/provider-settings-connection-1440.png`, `qa/provider-settings-routing-1440.png`, and `qa/provider-settings-wizard-1440.png`
- Viewports: `1440 × 1024` and `1100 × 782`, device scale factor `1`
- State: Simplified Chinese, cloud administrator, tenant and project selected, five realistic Provider records, OpenAI selected
- Render method: the production `SettingsWindow` and `ModelProviderWorkspace` were rendered by the Vite QA entry. The saved same-viewport captures were produced through Chrome DevTools Protocol; the current five-Provider overview and complete three-step add flow were freshly re-exercised in the user-selected in-app Browser after the contract fixes.

## Same-canvas comparison evidence

The approved compact source and the production `1100 × 782` capture were placed in one horizontal image before the final judgment. Five visible comparison points were checked:

1. The independent popup keeps the same dark backdrop, title bar, search field, close action, border, radius, and compact outer margin.
2. The information architecture remains a three-column hierarchy: settings rail, Provider catalog, and selected Provider detail.
3. The Provider catalog retains the same title, search, status filters, count row, selected-row treatment, icons, model counts, status copy, and attention colors.
4. The detail header preserves the breadcrumb, scope, copy action, add action, Provider identity, endpoint summary, credential badge, and five-tab navigation.
5. The compact overview keeps the same stacked health, model, and routing cards, including visible action affordances and the lower-card crop at the native viewport boundary.

The source capture is softer and records an earlier popup width. Production follows the latest source CSS contract: `min(1180px, 100vw - 52px)`, switching to `100vw - 28px` at the compact breakpoint. This accounts for the wider production shell at `1100` while preserving the source hierarchy and density.

## Required fidelity surfaces

- Typography and density: the Provider source sizes, weights, uppercase eyebrows, compact control heights, and tight list rhythm are retained.
- Layout: the `176 / 282 / flexible` desktop columns and `148 / 244 / flexible` compact columns match the source implementation. The detail body scrolls independently and no horizontal overflow is present.
- Color and state: cyan selection, green connected, amber attention, and red unhealthy or disabled states always include text and never rely on color alone.
- Assets and icons: the existing MemStack raster mark and Radix icon family are used. No CSS-art, emoji, inline SVG, or placeholder asset was introduced.
- Copy: English and Simplified Chinese strings come from the desktop i18n layer. Provider names, exact model IDs, endpoint hosts, and measured usage remain untranslated structured data.
- Responsiveness: both native viewports pass. The compact tenant card was adjusted to keep the tenant name on one truncated line instead of wrapping.
- Accessibility: the popup and wizard use modal dialog semantics; tabs, switches, checkboxes, form labels, status regions, disabled states, accessible names, focus outlines, Escape dismissal, and backdrop dismissal remain available.

## Real contract and fail-closed behavior

- Local Rust supports Provider type descriptors, list, create, revision-protected PUT/PATCH update, health aliases, source-attributed static model catalogs, tenant-checked empty usage, and configuration-only validation. The UI labels local validation as configuration validation and never claims that an outbound probe occurred.
- Cloud mode uses the real Provider type catalog, static model catalog, connection test, health check, update, create, and usage endpoints. The Desktop always sends `expected_revision`; the target Rust strangler route enforces it, while a direct legacy Python route currently ignores that compatibility field and exposes no CAS revision.
- Local catalogs identify built-in suggestions as `static-fallback`; an empty catalog without a source remains unavailable. No local `/models` network request is implied.
- Fast, coding, vision, fallback, and cloud routing mutations remain read-only because the current service contract does not expose those writes.
- A newly connected Provider is created active only after explicit validation and the final Add action; the UI does not claim unsupported per-role routing writes.
- API keys are accepted only in write requests and stored in the operating-system credential vault.
  Versioned records bind each secret to tenant, Provider, revision, type, endpoint, and auth method;
  stale or corrupt records fail closed. Provider responses expose only
  `credential_configured` plus a non-locating `system_vault` source enum, and the frontend
  allow-lists response fields before retaining them.
- OAuth, environment-secret references, live `/models` discovery, invented success rates, and synthetic activity feeds were not implemented because the current backend cannot support them truthfully.

## Interaction verification

- Provider search, All/Connected/Attention filters, selection, and tab reset: passed.
- Existing connection health check: passed; the verified result remains visible after the Provider health record refreshes.
- Connection edit boundary: passed; entering edit clears an earlier verification, draft changes clear verification, and Save remains disabled until the edited draft is validated.
- Model catalog load, search, enable switch, manual exact-ID entry, and explicit save: passed. Saving updates the Provider model count.
- Routing: passed; cloud-only unavailable mutations are visibly disabled, while the existing assignments remain inspectable.
- Usage: passed with authoritative request, token, latency, cost, and per-operation aggregates.
- Add Provider wizard: passed from Provider choice through credentials, declared probe or configuration-only validation, source-aware model selection, explicit active creation, selection of the new Provider, and success toast.
- Secret handling: passed; the dummy QA credential never appears in a response or screenshot.
- Browser console after a clean reload and core flow: no remaining runtime exception.
- Automated desktop tests: 346 passed.
- Desktop Rust library tests: 142 passed after adding explicit runtime selection, tenant isolation,
  restart recovery, credential redaction, schema migration, CORS preflight, and atomic endpoint/key
  coverage.
- Production TypeScript and Vite build: passed; only the existing large-chunk advisory remains.

## Comparison history

### Iteration 1 — blocked

- [P1] Models were presented as generic resources with one flat editor rather than Provider-first connection, catalog, routing, and usage layers.
- [P1] Settings did not consistently use the approved independent popup shell.
- [P1] Unsupported OAuth, live discovery, routing roles, and metrics risked becoming simulated product claims.
- [P2] Provider statuses and connection validation did not distinguish local configuration checks from real cloud probes.
- [P2] The previous Provider editor duplicated functionality and exceeded the repository file-size guidance.

Fixes: replaced the generic model resource path with the production Provider workspace, extracted focused components, removed the obsolete editor, connected only authoritative APIs, and added explicit unavailable/read-only states.

### Iteration 2 — passed

Browser QA found and fixed five implementation defects: a health refresh cleared the visible validation result; edit mode could reuse a stale verification; the initially selected wizard Provider did not load its model catalog; rate-limited Providers were labeled “Not checked”; and the compact tenant name wrapped across lines.

Post-fix overview, connection, routing, usage, model-save, and wizard checks show no actionable P0, P1, or P2 difference in the approved desktop range.

### Iteration 3 — passed

Contract review found and resolved four defects that screenshot comparison alone could not expose: update payloads omitted the `expected_revision` required by the target Rust gateway route; local Rust lacked the Desktop client's canonical PUT, health, model, usage, and draft-validation routes; a PUT preflight was blocked because CORS did not allow PUT; and static fallback catalogs were described like live discovery. Local endpoint validation now rejects malformed URLs, userinfo, query/fragment data, and remote plaintext HTTP before draft acceptance or persistence. Unknown Provider types fail closed. The legacy Python route's non-CAS behavior is documented as compatibility behavior rather than being presented as revision protection.

The existing same-canvas comparison remains current because the approved shell, hierarchy, geometry, and control layout did not change. A fresh in-app Browser pass confirmed five Provider rows, the overview tabs, API-key entry, successful declared cloud probe, and the third-step model choices. No actionable P0, P1, or P2 visual difference was introduced.

### Iteration 4 — passed

Runtime authority review removed the second LLM configuration source from Desktop config and Tauri
IPC. Provider create/update now manages only the connection; local execution changes only through the
explicit, revision-guarded runtime-selection action. Rust persists only `tenant_id → provider_id`,
keeps credentials in process memory, restores the selected Provider without restoring its secret, and
returns a sorted five-field redacted runtime projection. Provider binding, credential, and selection
reads share one atomic snapshot, so an endpoint update cannot execute with the previous key.

The final frontend scope guard now rejects a stale tenant/client before requesting a runtime status
refresh. A fresh in-app Browser pass at the production QA URL confirmed the independent popup,
five-row Provider catalog, overview geometry, and working Overview/Routing tab transition. The cloud
routing state remains truthfully read-only; local routing uses an explicit “Save and use for local
runtime” action. The approved visual hierarchy did not change, so the existing same-viewport combined
comparison remains current. Final contract audit: P0 0, P1 0, P2 0.

### Iteration 5 — passed: secure credential persistence

The prior process-memory-only credential behavior was replaced with the existing cross-platform
system-vault adapter (macOS Keychain, Windows Credential Manager, Linux persistent secret service).
Each desktop database now owns a persisted installation UUID. Vault accounts are one-way digests of
installation, tenant, Provider, revision, and binding identity, and each versioned record repeats those
fields for validation. The next revision is pre-written to its own account before the SQLite CAS; a
conflict removes only that candidate, while a process crash leaves the database's prior revision and
credential intact. Startup loads only the exact database revision and binding, so an uncommitted future
entry cannot replace or delete the authoritative secret. Credential writes run off the async request
executor, Provider mutations serialize before reading the current revision, and a disabled Provider
removes plaintext runtime material while retaining its vault secret for explicit reactivation.

Current-run same-viewport evidence:

- Source: `qa/provider-credential-persistence/01-source-connection-current.jpg`
- Implementation: `qa/provider-credential-persistence/02-implementation-connection-current.jpg`
- Viewport: `1280 × 720`, connection tab, configured API-key state

The combined visual review found no P0/P1/P2 regression in popup geometry, Provider navigation,
connection card hierarchy, authentication selection, masked credential field, endpoint section, or
primary actions. The implementation deliberately replaces the prototype's workspace-scoped secret
copy with tenant/device-accurate system-vault copy. Cloud mode separately identifies service-side
encrypted storage; legacy cloud responses without an authoritative `credential_configured` field now
remain unknown rather than being misreported as missing. Runtime evidence, rather than the static QA
fixture, proves persistence: the Provider remains `credential_configured: true` and
`configuration_valid` after reopening the SQLite store and runtime state, while the database, WAL,
responses, status projection, and debug output contain no canary secret. Dedicated tests also cover
same-revision concurrent updates, installation/profile isolation, and a simulated crash after the next
vault revision is written but before the SQLite revision changes.

Verification: 178 Rust tests, Clippy with warnings denied, 381 Desktop tests, TypeScript, and the Vite
production build passed. The existing Vite large-chunk advisory remains unchanged.

## Copy differences from the visual prototype

- “Connection verified” becomes “Configuration valid” in local mode because no outbound request is made.
- “Discovered models” becomes “Built-in catalog” or “Suggested models” when the backend marks the source as `static-fallback`.
- Unsupported routing writes say that the current server contract is read-only instead of presenting working Save controls.
- Usage cards show available raw server aggregates rather than prototype-only success-rate and recent-signal values.
- Provider creation confirms the active connection without implying that unsupported per-role routing assignments were written.

These differences are deliberate truthfulness constraints, not visual omissions.

## Remaining Provider-management findings

- [P1] Connection validation is configuration-only in the local runtime; implement a real outbound
  probe with redacted diagnostics and explicit timeout authority.
- [P1] Model discovery still uses a static fallback; implement authoritative Provider catalog refresh.
- [P1] OAuth, environment-backed credentials, advanced request policy, and the complete Provider/auth
  compatibility matrix remain unavailable rather than simulated.
- [P1] Workspace-scoped routing, executable Fast/Vision role selection, authoritative usage data, and
  Provider audit events remain to be implemented.

## Follow-up polish

- [P3] Code-split the existing desktop bundle in a later performance iteration; this does not affect Provider workflow correctness or visual fidelity.

provider credential persistence result: passed; overall provider settings result: in progress

---

# Authenticated no-project entry design QA

## Comparison target

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/settings-popup-workspace.png`
- Compact source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/settings-popup-workspace-1100.png`
- Implementation screenshot: unavailable in this iteration
- Intended viewports: `1440 × 1024` and `1100 × 782`, device scale factor `1`
- Intended state: authenticated cloud identity, tenant list available, no current project, Workspace Settings automatically open above the existing workspace overview

## Full-view comparison evidence

Blocked. The application source and automated tests verify the intended entry state, but the in-app Browser control required to capture the rendered implementation is not callable in this Codex session. No screenshot, HTTP health check, or source inspection is being substituted for visible comparison evidence.

## Focused-region comparison evidence

Blocked for the same reason. The workspace selector, current-context card, project empty state, apply control, close action, sidebar task action, and underlying overview cannot be judged from a same-viewport combined image in this iteration.

## Findings

- [P1] Rendered no-project state has not completed the visual comparison gate.
  - Location: authenticated desktop shell with Workspace Settings open.
  - Evidence: both source captures are available, but there is no current implementation capture to place beside them.
  - Impact: layout, disabled-state contrast, popup placement, copy wrapping, and close-to-overview continuity remain visually unverified.
  - Fix: capture the authenticated no-project state at both target viewports in the in-app Browser, combine each capture with its matching source, and resolve any P0/P1/P2 differences.

## Comparison history

### Iteration 1 — blocked

- The identity/workspace boundary, automatic Workspace Settings entry, project-scoped connection gate, and disabled New Task actions were implemented and passed automated tests.
- Visual comparison could not begin because the selected in-app Browser control is unavailable to this session.
- No visual pass is claimed from code or build evidence alone.

## Implementation checklist

- Capture the automatic Workspace Settings state at `1440 × 1024` and `1100 × 782`.
- Close the popup and capture the authenticated workspace overview with New Task visibly disabled.
- Reopen Workspace Settings from Configure and verify tenant switching, empty-project copy, and apply-button states.
- Check keyboard dismissal, focus, browser console errors, horizontal overflow, and copy wrapping.
- Compare source and implementation on one canvas and fix every P0/P1/P2 difference.

## Follow-up polish

- Defer P3 polish until the blocking comparison pass is available.

final result: blocked

---

# Session detail design QA

Date: 2026-07-17

Scope: authoritative conversation detail, narrative timeline, session controls, work canvases,
context rail, and composer.

## Visual sources

- Prototype: `design-prototype/memstack-desktop-agent-mission-control/qa/session-detail-redesign-1565-final.png`
- Implementation: `agi-stack/apps/desktop/qa/session-detail-mission-control-1565x900.jpg`
- Side-by-side comparison: `agi-stack/apps/desktop/qa/session-detail-mission-control-comparison-1565x900.jpg`

## Viewports and states

- `1565 x 900`: conversation surface with authoritative PostgreSQL-backed session data.
- `1100 x 800`: responsive conversation surface; document width and scroll width both 1100,
  with no page-level horizontal or vertical overflow.
- Tool and runtime groups are collapsed by default. Human input and plan review remain explicit.

## Findings resolved

- P0: none.
- P1: removed default expansion of raw task/error payloads; localized activity and failure copy;
  aligned the 76 px header, conversation/context split, context rail, and fixed composer.
- P1: aligned session projection read access with replay access; kept mutation capabilities
  fail-closed for read-only viewers; supported non-expiring pending HITL; redacted database errors.
- P1: projected cloud permission requests through a strict structured contract so authorized
  reviewers can inspect tool, action, risk, and description before approving once.
- P2: localized workspace-attempt states and unknown protocol identifiers; linked the Open task
  action to the exact authoritative task; removed governance identifiers from primary canvases.

## Verification

- Desktop tests: 340 passed.
- Desktop type check and production build: passed.
- Rust server tests: 636 passed.
- Rust formatting and Clippy with warnings denied: passed.
- Browser authority checks: no raw i18n keys, no raw task payload, no unavailable projection banner.

final result: passed
