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
- [P1] The full Provider/authentication matrix and advanced connection fields remain incomplete.
- [P1] Usage statistics and Provider mutation audit events still lack authoritative runtime data.

## Intentional product constraints

- Production starts with an empty email field rather than seeding a fictional account. The QA capture populated the source's example email to compare the same visual state.
- The prototype simulates SSO success. Production uses the native trusted local session only when that runtime is ready and otherwise fails closed with a localized message.
- Forgot-password and access-request controls remain visual-only, matching the source prototype, until dedicated product routes are specified.

## Follow-up polish

- [P3] None required for this approved desktop range.

final result: passed

---

# New Task → Agent Plan → Human Review design QA

Date: 2026-07-18

Scope: General Agent and Code Agent task definition, atomic local task-session creation, read-only
planning, persisted structured-plan polling, human plan preview, and the explicit approval boundary.

## Visual truth and implementation evidence

- Source component: `design-prototype/memstack-desktop-agent-mission-control/src/components/NewTaskFlow.jsx`
- Source styles: `design-prototype/memstack-desktop-agent-mission-control/src/styles.css`
- Production component: `agi-stack/apps/desktop/src/features/task/NewTaskFlow.tsx`
- Production stages: `agi-stack/apps/desktop/src/features/task/NewTaskFlowStages.tsx`
- QA route: `http://127.0.0.1:5173/qa/new-task-flow.html`
- Viewport: `1280 x 720`, device scale factor `1`, English, dark theme.
- Full-view comparisons:
  - `qa/new-task-atomic/comparison-define-2560x720.jpg`
  - `qa/new-task-atomic/comparison-generating-2560x720.jpg`
  - `qa/new-task-atomic/comparison-review-2560x720.jpg`
  - `qa/new-task-atomic/comparison-code-define-2560x720.jpg`
- Focused review comparison:
  `qa/new-task-atomic/comparison-review-focused-1640x560.jpg`

Every comparison places the live prototype on the left and the production component on the right
at the same viewport and state. The implementation capture uses the production `NewTaskFlow`
component with a strict diagnostic adapter that validates the scoped request, dual credentials,
mutation count, callbacks, immutable approval, and runtime errors; it is not a hand-built visual
substitute.

## Full-view comparison evidence

- Define: header height, 3-step progress geometry, 64.5/35.5 content split, field widths, sidecar,
  mode cards, footer, and primary action align with the source. General and Code both render the
  source composition; the production copy truthfully names Workspace and planning authority.
- Planning: the source and implementation share the same 70/30 canvas, title scale, progress line,
  four-stage stack, task brief, read-only authority statement, and footer. Code tasks retain the
  purple identity token rather than inheriting the General Agent cyan identity.
- Review: the 70/30 canvas, title block, summary card, 74-pixel plan rows, add-step control,
  authority sidecar, and footer align. The implementation retains a permission-profile choice
  because approval must bind an explicit runtime authority profile.
- No source-visible code-root or environment controls remain in Define. Those execution choices
  are intentionally deferred until after the plan boundary instead of expanding the source form.

## Focused-region comparison evidence

The review heading, work-task summary, four plan rows, and Add step action were cropped from both
current-run screenshots and placed together. Geometry and hierarchy match, while the comparison
also exposes the remaining authoritative-data gap: the source rows contain semantic descriptions,
expected outputs, and duration estimates, whereas the current persisted local plan tasks contain
only content, priority, and status.

## Required fidelity surfaces

- Typography: heading scale, eyebrow tracking, field labels, helper copy, task-row hierarchy, and
  footer labels now follow the source. Factual production wording is retained where the source
  simulates capabilities.
- Spacing and layout: header, split canvases, gutters, panel padding, row heights, footer, and
  responsive breakpoint pass current-run side-by-side inspection and have source-contract
  tripwires. The fixed in-app Browser
  viewport supplied the current-run 1280-pixel evidence; the source 1100-pixel breakpoint remains
  protected by the CSS contract test.
- Colors and tokens: flat near-black surfaces, slate borders, cyan planning/selection state, green
  completion state, and purple Code Agent identity match the source token roles. No gradient or
  invented elevation was added.
- Images and icons: the production flow uses the existing MemStack image asset and the project's
  Radix icon family. No text glyph, CSS-art, placeholder, or handcrafted SVG replacement was added.
- Copy and content: the brief and plan-authority copy are accurate. Complete review-row content,
  output labels, per-step duration, plan-level duration, and estimated cost are blocked by the
  authoritative plan-version schema rather than fabricated in the client.
- Accessibility: semantic labels, radio groups, progressbar values, live status, review focus, and
  keyboard-restored step editing remain present. Eight-pixel helper copy now exceeds 4.5:1 contrast.
  Programmatic pointer-driven review focus stays source-aligned; keyboard-driven review focus gets
  an explicit cyan indicator.

## Interaction and runtime verification

- Selected General Agent and Code Agent modes and entered realistic task briefs: passed.
- Generate plan synchronous double-click guard: passed.
- Local initialization produced exactly one `POST` to the scoped `task-sessions` endpoint: passed.
- No client-side Workspace create, Conversation create, mode PATCH, or initial-message replay was
  emitted after the atomic response: passed.
- Agent planning appeared before review, and review opened only after persisted versioned plan
  tasks arrived: passed.
- Approval remains a separate immutable-plan-version action; planning never grants write authority:
  passed.
- Current-run strict Browser trace: one task-session POST, one persisted-session callback, one Agent
  planning turn, and one Plan-ready activation before Review. A separate approval run emitted one
  approval POST bound to the previewed version and one Build-ready activation.
- Continue in background and Escape during the pending 600-millisecond atomic response both closed
  the dialog while the same session persisted, the Agent turn ran, and Plan activation completed:
  passed.
- Stable idempotency replay, changed-payload conflict, restart recovery, and transaction rollback:
  passed in Rust tests.
- Runtime and strict-contract diagnostics recorded by the QA page: no errors.
- Desktop tests: 401 passed. Source-contract tests are treated as tripwires, not substitutes for
  the Browser interaction and image-comparison evidence above.
- TypeScript type check and Vite production build: passed.
- Rust tests: 197 passed, including loopback probe cases.
- Rust formatting and Clippy with warnings denied: passed.

## Comparison history

### Iteration 1 — blocked

- [P1] Local initialization used multiple client mutations, allowing partial Workspace,
  Conversation, mode, or message state after a failed request.
- [P1] Idempotency replay rebuilt a response from mutable conversation state instead of preserving
  the original immutable response snapshot.
- [P1] Define showed code-root and environment controls absent from the approved source.
- [P2] Header height, Define and Review column ratios, plan-row height, planning title wrapping,
  Code Agent identity, and review focus treatment visibly diverged.
- [P2] Workspace metadata mixed untyped JSON values with typed fields and list/create routes did
  not consistently reject inactive tenant/project scope.

Fixes: added one strict Rust task-session transaction and immutable receipt snapshot; revalidated
user, tenant, project, context revision, and active scope inside the transaction; made typed fields
authoritative; replaced the local split mutation chain with one idempotent POST; removed the
source-inconsistent Define controls; and aligned the measured geometry, tokens, and focus behavior.

### Iteration 2 — blocked on authoritative plan richness

An independent regression review found that Continue in background and Escape could invalidate the
pending operation after the task-session transaction committed, and that the original visual
harness did not exercise authority callbacks or approval. The close boundary now preserves only
submitted work, while external closure still invalidates its epoch. The strict QA adapter now
checks production workspace authority, one scoped mutation, session persistence, Agent dispatch,
activation, version-bound approval, and errors. Browser runs cover normal approval plus both
background-close paths.

Current-run side-by-side comparisons close the remaining actionable layout and interaction differences.
The remaining P1 is not safe to solve as presentation-only data: the persisted plan version does
not yet carry structured step detail, expected output, estimated minutes, or plan-level time/cost.
Showing the source values would require fabricating execution evidence in the client.

## Remaining blocker

- [P1] Extend the immutable plan-version contract with structured `detail`, `expected_output`, and
  `estimated_minutes` fields per step plus authoritative plan-level time/cost or an explicit
  unavailable state. Populate those fields through the Agent structured tool call, persist them,
  bind approval to that exact version, and render them in the review surface.

final result: blocked

---

# Tenant → project → workspace → conversation hierarchy authority design QA

Date: 2026-07-18

Scope: authoritative tenant and project context, production workspace/conversation tree, workspace
overview entry, and settings context-switch interaction.

## Visual sources

- Prototype: `qa/hierarchy-source-workspace-1325.png`
- Implementation: `qa/hierarchy-implementation-workspace-final-1325.png`
- Side-by-side comparison: `qa/hierarchy-workspace-final-comparison-1325.png`
- Viewport: `1325 x 964`, device scale factor `1`

## Findings resolved

- P0: a fresh Rust catalog now opens `northstar / desktop-client`, matching the prototype instead
  of showing the legacy `local / local-project` context. Only a truly untouched legacy default is
  migrated; contexts with prior sessions, context events, or a nonzero revision are preserved.
- P1: React hydration and settings switching now accept only server-issued workspace context and
  revision authority. The client no longer manufactures a fallback context after a missing route.
- P1: settings tenant/project choices expose selected state and remain frozen while an authority
  switch is pending, preventing overlapping context mutations.
- P1: the production Radix scroll viewport now owns the full remaining navigation height. The tree
  viewport increased from 168 px to 312 px in the audited state, keeping both workspaces and their
  conversation children available without the focus ring shrinking layout.
- P2: removed the obsolete direct workspace/session creation paths. Creation remains in the governed
  New Task → Agent Plan → Human Review flow.
- P2: the hierarchy QA route now renders `DesktopSidebar` itself rather than a hand-coded visual
  substitute, so the comparison exercises production tree behavior and styling.

## Interaction verification

- Both workspace roots are visible in the production tree.
- Collapse and re-expand preserve the selected workspace and conversation state.
- Selecting a conversation produces the production active-row treatment and changes the QA overview
  selection without changing tenant/project authority.
- Settings choices lock during apply and depend on the authoritative switch response.
- No P0/P1/P2 visual mismatch remains in the hierarchy canvas at the audited viewport.

## Automated verification

- Desktop tests: 387 passed.
- Rust tests: 188 passed serially, including loopback provider probes.
- TypeScript check and Vite production build: passed.
- Rust formatting and Clippy with warnings denied: passed.
- The existing Vite large-chunk advisory remains P3 performance follow-up work.

### Iteration 2 — passed: authoritative identity catalogs

Cloud and local Rust tenant/project catalogs now request every backend page at the declared 100-row
maximum before login hydration or Workspace Settings resolves the active context. Each page must
preserve the requested page number and size, a stable total, forward progress, unique IDs, and valid
typed rows. Project rows must match the requested tenant exactly. Missing metadata, duplicate rows,
changing totals, malformed records, and cross-tenant projects fail closed with a gateway-contract
error instead of becoming an empty or incomplete context.

The authenticated no-project QA adapter now implements the real page contract. No component, style,
or visible state changed, so the existing same-viewport hierarchy comparison remains current; this
iteration corrects the data boundary underneath that approved UI.

Verification: the new contract tests failed against the prior first-page and permissive parsing
behavior, then passed after implementation. The complete Desktop suite passes 425/425, along with
production TypeScript and the Vite build. The existing Vite large-chunk advisory is unchanged.

## Remaining architecture work outside this slice

- Make workspace creation metadata and initial conversation binding one atomic Rust transaction.
- Add authoritative workspace roster/agent endpoints plus bounded pagination and strict scope
  validation for workspace and conversation collections.
- Replace remaining demo execution phases with structured run-state projection as those backend
  contracts become available.

final result: passed for the hierarchy authority slice; overall desktop reconstruction remains in progress

---

# Workspace model-routing policy design QA

Date: 2026-07-18

Scope: Settings -> Models -> OpenAI -> Routing, executable workload-role assignment, ordered
fallback editing, timeout failover, save/conflict feedback, local-runtime compatibility, and exact
tenant -> project -> workspace scope.

## Visual truth and implementation evidence

- Current source visual truth: `agi-stack/apps/desktop/qa/workspace-routing/source-1280x720.jpg`
- Pre-fix implementation: `agi-stack/apps/desktop/qa/workspace-routing/before-1280x720.jpg`
- Current clean implementation: `agi-stack/apps/desktop/qa/workspace-routing/after-1280x720.jpg`
- Current edited implementation with the primary action active:
  `agi-stack/apps/desktop/qa/workspace-routing/after-dirty-1280x720.jpg`
- Viewport: `1280 x 720`, device scale factor `1`, captured from the user-selected in-app Browser.
- State: Simplified Chinese, dark theme, Settings modal, Models selected, OpenAI selected, Routing
  tab selected. The implementation uses the local QA authority with OpenAI, Anthropic, and an
  OpenAI-compatible local gateway.

## Full-view comparison evidence

The source and implementation screenshots were opened together in one comparison input. The
settings frame, 183-pixel section rail, 292-pixel provider list, provider detail column, header,
five-tab strip, two-column role grid, fallback card, dark palette, border density, and vertical
rhythm align at the same visible crop. No persistent control is hidden by viewport overflow.

The implementation intentionally shows three authoritative local Provider records instead of the
source's five-row illustrative cloud catalog, and it preserves the exact runtime model IDs returned
by those records. The authority label, detail scope, role descriptions, two-by-two selector grid,
and fallback rows now match the source's Workspace Routing design. Default, Fast, Coding, and
Vision are all enabled and persisted for the selected workspace.

## Focused-region comparison evidence

The provider header, tabs, role card, four selectors, fallback card, and first ordered fallback
were cropped from the actual source and implementation screenshots and opened together. The
following surfaces remain readable at native scale:

- provider icon, title, connection status, endpoint summary, and tab alignment;
- workload eyebrow, heading, explanatory copy, and save action;
- two-by-two role geometry, labels, helper copy, select height, radii, and borders;
- fallback order numbering, select geometry, and row controls.

The previous up/down icon group has been removed. Each fallback row now matches the source's
number + selector + localized Remove action, while the numbered selectors themselves define the
ordered sequence. Save remains disabled only in a clean state and becomes the source-visible cyan
primary action after any role or fallback change.

## Required fidelity surfaces

- Fonts and typography: the existing desktop sans-serif stack, heading weights, compact eyebrow,
  tab labels, helper copy, and exact model IDs preserve the source hierarchy and wrapping.
- Spacing and layout rhythm: frame margins, three-column settings layout, provider header height,
  tab rhythm, two-column role grid, card padding, fallback rows, and radii match the source. The
  shorter provider list is an intentional local-runtime data difference.
- Colors and visual tokens: flat near-black surfaces, slate borders, muted labels, green
  configuration-valid state, and cyan selection/action tokens remain
  consistent. No gradient or invented elevation was introduced.
- Image quality and asset fidelity: the existing MemStack and provider raster/icon assets are
  retained; no visible source asset was replaced with CSS art, text glyphs, or placeholder boxes.
- Copy and content: Workspace Routing, all four role names/descriptions, fallback rationale,
  Provider context, and success feedback use the source copy in English and Simplified Chinese.
  Exact model IDs remain authoritative runtime data. Local validation says `Configured` and never
  fabricates an external connectivity probe.
- Accessibility: the Provider tabs use the tab pattern; role and fallback selectors have semantic
  labels; fallback removal has a localized accessible name; errors use alerts and save
  confirmation uses a status region.

## Interaction verification

- Changed the Coding route from Anthropic to OpenAI: passed; Save became available.
- Fast and Vision selectors: passed; both are enabled, preserve their structured targets, and never
  depend on message-text heuristics.
- Removed and added a fallback: passed; duplicate choices stayed disabled and row numbering updated.
- Saved the policy: passed; the dirty state reset, Save became disabled, and the localized
  `Workspace routing policy saved` status appeared.
- Candidate authority: passed; only providers projected by the local API as
  `configuration_valid` are selectable. Persisted unavailable targets remain visible but disabled.
- Failover execution: passed in Rust tests; each candidate has a 45-second bound, timeout advances
  to the next target, and a single candidate is also bounded.
- Conflict recovery: passed in source and automated contract tests; a 409 reloads both provider
  roster and policy, then refreshes the runtime projection under the original scope guard.
- Legacy runtime selection: passed in Rust tests; it remains a tenant compatibility baseline and
  cannot overwrite an initialized workspace policy or leak one workspace's choice into another.
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

### Iteration 3 — passed for tenant-scoped runtime truth

The post-fix full-view and focused comparisons show no actionable P0, P1, or P2 visual findings.
The remaining differences are the explicit tenant scope, locally supported provider roster, exact
runtime model IDs, disabled reserved roles, dirty-save state, and usable reorder controls described
above.

### Iteration 4 — passed for workspace authority and four executable roles

- Added a non-destructive workspace routing table keyed by tenant, project, and workspace.
- GET and PUT validate the active hierarchy; frontend responses are rejected when any returned scope
  differs from the selected workspace.
- The four role selectors are enabled and use the same source-visible copy and geometry.
- The Provider workspace resets Radix's inherited line height to the source's normal line box;
  measured identity height is `140.9 px` in the source and `139.4 px` in production, with the tab
  strip and routing canvas landing within two pixels at the same viewport.
- Explicit snake_case `workload_role` selects Fast or Vision without parsing user text. The role is
  included in the client-turn idempotency hash, so a changed role cannot replay another execution.
- A saved workspace route does not update the tenant selection or write its model into a shared
  Provider binding. A later workspace therefore inherits only the original tenant baseline.
- Provider compatibility validation covers all workspace policies, the legacy tenant policy, and
  the selection-derived pre-migration baseline.
- Current same-viewport comparison found no actionable P0, P1, or P2 geometry, hierarchy, copy,
  control, focus, clipping, or overflow difference. Provider roster size and exact model IDs remain
  authoritative-data differences.
- Browser interaction changed Vision, activated Save, persisted the policy, restored the clean
  state, and exposed the localized success status. Browser logs contain no warning or error.
- Verification: 402 frontend tests, TypeScript/Vite production build, 201 Rust tests, Rustfmt, and
  Clippy with warnings denied all passed.

## Findings

No actionable P0, P1, or P2 findings remain.

## Follow-up polish

- [P3] Add authoritative per-workspace usage and Provider mutation audit projections when the
  runtime exposes those records; do not synthesize them in the UI.

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
- Authentication source-fidelity captures:
  `qa/provider-auth-source-fidelity/source-model-provider-connection-1440x1024.png`,
  `qa/provider-auth-source-fidelity/implementation-provider-auth-edit-1440x1024.png`, and
  `qa/provider-auth-source-fidelity/comparison-source-implementation-1440x1024.png`
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

- Local Rust supports Provider type descriptors, list, create, revision-protected PUT/PATCH update,
  health aliases, source-attributed model catalogs, tenant-checked usage, and explicit connection
  validation. Validation returns `probed` evidence so the UI distinguishes a real outbound probe
  from credential or configuration failure.
- Cloud mode uses the real Provider type catalog, static model catalog, connection test, health check,
  update, create, and usage endpoints. The Desktop and Web editors send `expected_revision`; local
  Rust, target Rust, and Python all expose a revision and enforce the comparison atomically before
  mutation. A stale update returns `409` instead of rebinding a credential to an overwritten endpoint.
- Local catalogs identify built-in suggestions as `static-fallback`; an empty catalog without a source remains unavailable. No local `/models` network request is implied.
- Fast, coding, vision, fallback, and cloud routing mutations remain read-only because the current service contract does not expose those writes.
- A newly connected Provider is created active only after explicit validation and the final Add action; the UI does not claim unsupported per-role routing writes.
- API keys are accepted only in write requests and stored in the operating-system credential vault.
  Versioned records bind each secret to tenant, Provider, revision, type, endpoint, and auth method;
  stale or corrupt records fail closed. Provider responses expose only
  `credential_configured` plus a non-locating `system_vault` source enum, and the frontend
  allow-lists response fields before retaining them.
- Environment-secret references are implemented for the local and target Rust runtimes. Only the
  allow-listed variable name is persisted or returned; the value is resolved at runtime and remains
  in process memory. Missing values return `probed: false` without a network request. Gateway-owned
  CRUD persists environment references in Rust; Python Agent bootstrap and persisted health checks
  consume those structured references without decrypting the no-key sentinel. The direct Python
  compatibility CRUD surface still does not advertise or write environment auth. OAuth remains
  visible but disabled as “Backend not configured”; no browser window or simulated OAuth flow exists.
  Invented success rates and synthetic activity feeds remain absent.

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

### Iteration 6 — passed: truthful authentication matrix

The Connection surface now matches the approved three-card source hierarchy for OpenAI and
Anthropic: OAuth, API key, and Environment secret. Capability descriptors keep supported and
explicitly unavailable methods separate. OAuth is always rendered as a disabled card with a
backend-not-configured explanation; the client rejects any attempted OAuth mutation before issuing
a request. Switching methods clears mutually exclusive draft credentials and invalidates prior probe
evidence.

Environment authentication stores and returns only `environment_variable`. Local and target Rust
resolve the value at probe/runtime boundaries, reject unsupported variable names where the runtime is
multi-tenant, never write the value to SQLite or the system vault, and reconstruct the reference after
restart. Environment availability is driven by `validation.probed`: a reachable provider may fail for
another reason without incorrectly labeling the secret missing. The Python compatibility descriptor
shows Environment as unavailable for persisted providers rather than advertising a mode its current
LiteLLM consumers cannot execute.

The source and implementation were captured in the same `1440 × 1024` Connection/Edit state and
placed in one `2880 × 1024` comparison image before judgment. Popup geometry, three-column hierarchy,
Provider navigation, authentication-card alignment, endpoint section, and actions remain source
aligned. A fresh `1100 × 800` in-app Browser pass confirmed a single-column authentication stack,
usable scrolling, no horizontal overflow, and no console errors. No visual or interaction P0/P1/P2
finding remains in this authentication scope.

Verification: 409 Desktop tests; 34 local Rust Provider tests; 31 target Rust Provider API tests; 72
Python Provider tests; TypeScript, Rustfmt, Clippy with warnings denied, Ruff, Mypy, Pyright, and golden
contract parity passed.

### Iteration 7 — passed: cross-runtime authentication boundary

The final contract pass converted public Provider configuration from an open-ended secret denylist
to an explicit safe-field projection in target Rust and Python. Unknown config keys, nested
`provider_options`, headers, tokens, credentials, and future unrecognized fields remain server-side.
Create, update, and probe bodies reject unknown fields instead of silently accepting misspelled or
credential-like input.

Environment authentication is now origin-bound. `OPENAI_API_KEY` can be resolved only for the
official OpenAI HTTPS origin, and `ANTHROPIC_API_KEY` only for the official Anthropic HTTPS origin.
OpenAI-compatible and custom endpoints require an explicit endpoint-bound API key or no-auth local
configuration. Userinfo, query, fragment, remote plaintext HTTP, and historical unsafe endpoints are
rejected or hidden before any credential is resolved or sent.

Environment detection returns the exact allow-listed variable name plus availability, never its
value. Web and Desktop consume this as a reference and render authentication choices from the
Provider capability descriptor. Create, update, and probe requests keep API-key, Environment, and
No-auth fields mutually exclusive. Existing credentials are reusable only while Provider type,
authentication method, endpoint, and (for Environment) variable binding remain unchanged.

Python now matches the Rust optimistic-concurrency contract with an exact microsecond revision,
row-locked comparison, monotonically advanced `updated_at`, and `409` conflict response. Saved local
no-auth Providers execute their health probe with an empty credential rather than failing before the
endpoint adapter is called. Both Web Provider editors submit the loaded revision.

Default-Provider create and update operations now share an operation-scoped PostgreSQL transaction
advisory lock. Insertion, stale-revision validation, prior-default clearing, and revision advancement
commit atomically, including the empty-table create/create case. Endpoint updates use a three-state
contract: omitted retains the binding, explicit `null` or blank clears it to SQL `NULL`, and a valid
string replaces it. Anthropic `/v1` probe paths append idempotently. Providers without a supported
network probe return `configuration_valid` with `probed: false` after structural and security
validation; they never simulate a successful request.

Verification: 409 Desktop tests and Desktop TypeScript; 38 local Rust Provider tests and Clippy with
warnings denied; 37 target Rust Provider API tests, a PostgreSQL NULL-persistence integration test,
and Clippy with warnings denied for server and Postgres adapter; 150 focused Python unit/integration
tests using the repository `.env`, plus real PostgreSQL two-session create/create and create/update
default races ending with exactly one default. Ruff, Mypy, and Pyright report zero errors. A clean
baseline plus the eight Provider Web files passes TypeScript, ESLint, Prettier, and 11/11 focused
tests. The shared dirty worktree's full Web check remains blocked only by unrelated in-progress
`useUnifiedAgentStatus.ts` and timeline-store mock changes (22 failures; 3,537 other tests pass).

### Iteration 8 — passed: fail-closed capability loading and no-probe parity

The final security audit removed the remaining implicit-auth fallback. Both Web Provider editors now
hold authentication and saving closed while the capability descriptor is loading, when the request
fails, when the selected Provider descriptor is absent, or when `auth_methods` is explicitly empty.
The UI distinguishes each state in English and Simplified Chinese. Free-form Provider JSON, free-form
embedding options, plaintext RTC/access/speech credentials, and unknown response config fields are
not rendered or submitted; the client projects only the backend's explicit public-safe schema.

Rust and Python now share the same standalone `embedding_config` update contract: submitted public
safe fields replace the prior public set, omitted public fields are cleared, and historical private
metadata remains server-side. Rust accepts every explicitly supported official base path (including
Anthropic root and `/v1`) while environment detection validates transport, origin, and path before it
exposes a variable reference. Unsafe records remain visible only as unavailable repair state and never
resolve or return a secret.

Desktop, Web, Rust, and Python now agree on providers that do not support an outbound probe. Draft and
persisted checks return or project `configuration_valid` with `probed: false`; Desktop avoids a second
health request after create, and every UI says “Configuration validated / 配置已校验” rather than
“Connected” or “Error”.

Verification: 409/409 Desktop UI tests, 207/207 Desktop Rust tests, and Desktop TypeScript; 48/48 Rust
server Provider tests; 5/5 live PostgreSQL adapter tests using the repository `.env` and covering CRUD,
health ordering, default-provider atomicity, duplicate names, assignments, and usage; Rustfmt and
Clippy with warnings denied; 235/235 focused Python tests, Ruff, Pyright with zero errors, and i18n
validation; 29/29 focused Web/i18n tests plus isolated TypeScript, ESLint, and Prettier. The shared
worktree's full Web type check still has the
three unrelated `useUnifiedAgentStatus.ts` errors, and full Mypy currently reports four unrelated
baseline errors in agent client-turn persistence and chat acknowledgement handling.

### Iteration 9 — passed: workspace-route authority and truthful usage availability

The Desktop now derives its current LLM projection from the selected workspace routing policy for
all four consumers: execution, Settings, the runtime monitor, and the session composer. The previous
tenant-level runtime selection is no longer exposed by the frontend client or Provider model. Its
Rust route and persistence record remain compatibility-only so existing installations can migrate a
baseline once without overwriting a workspace policy.

Provider usage reads are available to every tenant member with Provider read access; mutation
controls remain manager-only. The local Rust compatibility endpoint now returns
`availability: unavailable` when no authoritative aggregate source exists. Frontend normalization
preserves that state and never turns an empty payload into zero requests, tokens, latency, or spend.
Settings navigation copy was also aligned with the current source in English and Simplified Chinese.

Current same-viewport evidence from the user-selected in-app Browser:

- Source: `qa/provider-settings-authority-source-1280x720.jpg`
- Implementation: `qa/provider-settings-authority-implementation-1280x720.jpg`
- Combined review input: `qa/provider-settings-authority-comparison-final-2560x720.jpg`
- Viewport: `1280 × 720`, Models / Provider Overview state

The combined image was opened and reviewed as one canvas. Popup geometry, settings rail, Provider
catalog, selected-row treatment, detail hierarchy, tabs, cards, spacing, borders, typography, and
actions remain source aligned. The implementation intentionally shows three authoritative Provider
records instead of the source fixture's five mock records, together with their real identifiers and
dates. Overview → Usage → Overview interaction passed, and no runtime error overlay appeared.

Verification: 422/422 Desktop UI and contract tests, Desktop TypeScript, Vite production build,
Rustfmt, Clippy with warnings denied, and 215/215 Desktop Rust tests passed. The existing Vite
large-chunk advisory remains unchanged. This iteration has no remaining P0/P1/P2 regression; the
separate P1 for authoritative usage aggregation and Provider audit events remains open.

## Copy differences from the visual prototype

- Configuration-only fallback results remain explicitly labeled when an outbound probe is unavailable.
- “Discovered models” becomes “Built-in catalog” or “Suggested models” only when the backend marks the source as `static-fallback`.
- Cloud routing writes remain read-only when the server contract omits mutation; local workspace routing is editable.
- Usage cards show available raw server aggregates rather than prototype-only success-rate and recent-signal values.
- Provider creation confirms the active connection without implying that unsupported per-role routing assignments were written.

These differences are deliberate truthfulness constraints, not visual omissions.

## Remaining Provider-management findings

- [P2] OAuth and advanced request policy remain unavailable rather than simulated until dedicated,
  structured backend capabilities and encrypted storage are implemented.
- [P1] Authoritative workspace usage data and Provider audit events remain to be implemented.

## Follow-up polish

- [P3] Code-split the existing desktop bundle in a later performance iteration; this does not affect Provider workflow correctness or visual fidelity.

provider authentication result: passed; overall provider settings result: in progress

---

# Authenticated no-project entry design QA

Date: 2026-07-18

Scope: authenticated cloud identity with an available tenant roster but no authoritative project
context. Workspace Settings opens automatically above a truthful no-project workspace overview.

## Reference roles

- Large-screen design-language and geometry reference:
  `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/settings-popup-workspace.png`
  (`1440 × 1024`).
- Compact design-language and geometry reference:
  `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/settings-popup-workspace-1100.png`
  (`1100 × 800`).
- Both source references contain a selected project and populated project cards. They are not
  same-state visual truth for the no-project flow. They validate window placement, rail/content
  proportions, spacing, typography, borders, density, and responsive behavior only.
- Empty-project copy, automatic entry, disabled actions, and close-to-overview continuity are a
  source-language extension required by the real Rust API contract.

## Implementation evidence

- Automatic entry, `1440 × 1024`:
  `qa/workspace-no-project/implementation-auto-open-1440x1024.png`
- Empty tenant project list, `1440 × 1024`:
  `qa/workspace-no-project/implementation-empty-project-1440x1024.png`
- Closed settings and truthful overview, `1440 × 1024`:
  `qa/workspace-no-project/implementation-closed-1440x1024.png`
- Source-matched compact viewport, `1100 × 800`:
  `qa/workspace-no-project/implementation-auto-open-1100x800.png`
- Additional product target, `1100 × 782`:
  `qa/workspace-no-project/implementation-auto-open-1100x782.png`

The source and implementation captures were reviewed together at both source viewports. At
`1440 × 1024`, the implementation window is `1180 × 820` at `(130, 102)`. At `1100 × 800`, it is
`1072 × 772` at `(14, 14)`. These match the source geometry. The compact rail remains `148 px`, the
tenant and project choices collapse to one column, and the `58 px` context action remains visible at
the bottom of the window. Document width equals viewport width in all three implementation captures;
there is no page-level horizontal overflow.

## Interaction evidence

- The first authenticated no-project render automatically opens Workspace Settings and focuses the
  settings search field.
- Selecting Northstar Labs produces the explicit “no projects available” state and keeps Switch
  workspace disabled.
- Closing settings retains the signed-in shell, renders a dedicated no-project overview, and keeps
  both New Task entry points disabled.
- Configure reopens Workspace Settings. Escape closes it and returns focus to Configure when a
  trigger exists.
- Browser console verification completed with zero warnings and zero errors.

## Findings resolved

- [P1] Consumed only the structured Rust `404 workspace_context_unavailable` response as an
  authenticated no-project state; unrelated authentication and context failures still fail closed.
- [P1] Added deterministic real-component QA coverage for automatic entry, empty tenant projects,
  closed overview continuity, and disabled task creation.
- [P1] Restored authentication-generation and request-scope fences after asynchronous project and
  context reads so logout or account replacement cannot receive stale context writes.
- [P1] Corrected the compact sticky action from an off-canvas offset to `bottom: 0`, matching the
  source compact layout.
- [P2] Replaced misleading current-project and empty-workspace language across the title bar,
  sidebar, workspace tree, overview, and settings content.
- P0: none. No remaining actionable P1 or P2 visual finding was observed in the implemented state.

## Comparison history

### Iteration 1 — evidence audit

- Corrected the earlier claim that the two populated source captures were no-project visual truth.
- Confirmed that neither the source prototype nor the existing Provider fixture could render the
  required state.

### Iteration 2 — rendered extension pass

- Added a deterministic authenticated no-project fixture backed by the production components.
- Completed full-view and focused interaction review at `1440 × 1024`, `1100 × 800`, and
  `1100 × 782`.
- Fixed the compact sticky action and repeated the responsive and console checks.

Same-state source truth remains unavailable by source design; this pass validates a faithful
source-language extension and must not be cited as pixel identity for state-specific source content.

final result: passed

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
