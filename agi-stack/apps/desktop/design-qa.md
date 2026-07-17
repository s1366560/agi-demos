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

No actionable P0, P1, or P2 findings remain.

## Intentional product constraints

- Production starts with an empty email field rather than seeding a fictional account. The QA capture populated the source's example email to compare the same visual state.
- The prototype simulates SSO success. Production uses the native trusted local session only when that runtime is ready and otherwise fails closed with a localized message.
- Forgot-password and access-request controls remain visual-only, matching the source prototype, until dedicated product routes are specified.

## Follow-up polish

- [P3] None required for this approved desktop range.

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
- Render method: the production `SettingsWindow` and `ModelProviderWorkspace` were rendered by the Vite QA entry and exercised through Chrome DevTools Protocol. The in-app Browser control was unavailable to this session, so Chrome for Testing was used without Playwright.

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

- Local Rust supports Provider list, create, revision-protected update, and configuration-only validation. The UI labels local validation as configuration validation and never claims that an outbound probe occurred.
- Cloud mode uses the real Provider type catalog, static model catalog, connection test, health check, update, create, and usage endpoints.
- Local model discovery and usage return explicit unavailable states without making a network request.
- Fast, coding, vision, fallback, and cloud routing mutations remain read-only because the current service contract does not expose those writes.
- A newly connected Provider is created inactive and is not silently made the runtime default.
- API keys are accepted only in write requests, cleared after use, and never hydrated from Provider responses. QA responses deliberately strip submitted secrets.
- OAuth, environment-secret references, live `/models` discovery, invented success rates, and synthetic activity feeds were not implemented because the current backend cannot support them truthfully.

## Interaction verification

- Provider search, All/Connected/Attention filters, selection, and tab reset: passed.
- Existing connection health check: passed; the verified result remains visible after the Provider health record refreshes.
- Connection edit boundary: passed; entering edit clears an earlier verification, draft changes clear verification, and Save remains disabled until the edited draft is validated.
- Model catalog load, search, enable switch, manual exact-ID entry, and explicit save: passed. Saving updates the Provider model count.
- Routing: passed; cloud-only unavailable mutations are visibly disabled, while the existing assignments remain inspectable.
- Usage: passed with authoritative request, token, latency, cost, and per-operation aggregates.
- Add Provider wizard: passed from Provider choice through credentials, connection test, discovered-model selection, inactive creation, selection of the new Provider, and success toast.
- Secret handling: passed; the dummy QA credential never appears in a response or screenshot.
- Browser console after a clean reload and core flow: no remaining runtime exception.
- Automated desktop tests: 116 passed.
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

## Copy differences from the visual prototype

- “Connection verified” becomes “Configuration valid” in local mode because no outbound request is made.
- Unsupported routing writes say that the current server contract is read-only instead of presenting working Save controls.
- Usage cards show available raw server aggregates rather than prototype-only success-rate and recent-signal values.
- Provider creation confirms the inactive state instead of implying immediate runtime activation.

These differences are deliberate truthfulness constraints, not visual omissions.

## Findings

No actionable P0, P1, or P2 findings remain.

## Follow-up polish

- [P3] Code-split the existing desktop bundle in a later performance iteration; this does not affect Provider workflow correctness or visual fidelity.

provider settings final result: passed

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
