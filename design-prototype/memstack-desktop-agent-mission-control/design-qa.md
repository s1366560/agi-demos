# Design QA — My Work Mission Control

## Comparison contract

- Source of truth: `../../docs/product/desktop-agent-ui/visual-directions/02-my-work-mission-control.png`
- Implementation state: `qa/work-implementation.png`
- Combined comparison: `qa/work-comparison.png`
- Secondary scenario: `qa/code-implementation.png`
- Compact desktop evidence: `qa/compact-1100.png`
- New-task design set: `qa/task-create-define.png`, `qa/task-plan-generating.png`, `qa/task-plan-review.png`, `qa/task-plan-review-code.png`, `qa/task-started.png`, `qa/task-plan-review-1100.png`
- New-task full comparison: `qa/task-flow-comparison.png`
- New-task focused comparison: `qa/task-flow-focused-comparison.png`
- Management design set: `qa/manage-models.png`, `qa/manage-skills.png`, `qa/manage-plugins.png`, `qa/manage-agents.png`, `qa/manage-create-agent.png`
- Management full comparison: `qa/manage-comparison.png`
- Management focused comparison: `qa/manage-focused-comparison.png`
- Management compact desktop evidence: `qa/manage-compact-1100.png`
- Settings/i18n evidence: `qa/settings-general-zh.png`, `qa/settings-general-en-viewport.png`, `qa/settings-models-zh-final.png`, `qa/settings-models-zh-final-1100.png`
- Settings focused comparison: `qa/settings-source-rail-focus-ffmpeg.png`, `qa/settings-implementation-rail-focus-ffmpeg.png`
- Provider-first model configuration: `qa/model-provider-audit-before.png`, `qa/model-provider-overview-final.png`, `qa/model-provider-connection.png`, `qa/model-provider-add-wizard.png`, `qa/model-provider-routing-1100.png`
- Provider detail comparison: `qa/model-provider-before-detail.png`, `qa/model-provider-after-detail.png`
- Login and workspace context: `qa/login-screen.png`, `qa/login-screen-1100.png`, `qa/settings-popup-account.png`, `qa/settings-popup-workspace.png`, `qa/settings-popup-workspace-1100.png`
- Settings popup comparison: `qa/settings-fullpage-before-popup.png`, `qa/settings-popup-account.png`, `qa/settings-before-popup-focused.png`, `qa/settings-popup-focused.png`
- Primary viewport: 1440 × 1024
- Compact viewport: 1100 × 800
- Compared states: baseline Work Mission Control; Work and Code task briefs; Agent planning; human plan review; approved plan starting; Models, Skills, Plugins, and Agents management; governed draft creation.
- Added journey states: unauthenticated login; validation; trusted-session restore; Account settings; Tenant → Project selection; context apply; profile sign-out.

## Pass history

### Pass 1

- P1 — Layout: the initial sidebar and task queue occupied 512 px versus roughly 415 px in the selected direction, compressing the task detail and weakening its hierarchy.
  - Fix: reduced the navigation and queue tracks to 150 px and 265 px.
- P1 — Content density: the detail pane omitted the progress, sources, and blocker row from the selected direction and left a large empty region.
  - Fix: added the three-card execution insight row and a source-aware blocker action.
- P2 — Artifact anatomy: the draft preview lacked the reference design's left document outline.
  - Fix: added the outline rail and retained a readable, source-linked report body.
- P2 — Typography: queue summaries and primary task titles were undersized.
  - Fix: increased the affected text tokens while preserving the dense desktop rhythm.

### Pass 2

- P1 — Viewport resilience: at 1100 × 800 the task detail expanded beyond its parent and pushed the action dock below the viewport.
  - Fix: constrained the task detail to `100vh`, added `min-height: 0`, and kept the center content independently scrollable.
- P2 — Product copy: the Work review action used the Code label “Review changes.”
  - Fix: changed it to “Review brief”; Code keeps “Review changes.”

### Pass 3 — Plan-first task creation

- P1 — Post-approval continuity: the first implementation returned a newly approved task to the pre-existing Q3 brief artifact, which made the plan-to-run handoff visibly inconsistent.
  - Fix: persisted the approved plan on the new task and added an execution-plan artifact with active/queued steps, run contract, context count, and limited-authority state. Evidence: `qa/task-started.png`.
- P2 — Human control: plan-row edit controls and “Ask agent to revise” were initially visual-only.
  - Fix: added inline title/detail editing with save/cancel, step enable/disable, add-step, live time recalculation, and a planning revision loop.
- P2 — Mode switching: selecting Code retained the seeded Work brief and produced a semantically mismatched task.
  - Fix: when the user has not changed the seeded brief, Work/Code selection now swaps to coherent mode-specific examples; user-authored text remains untouched.

### Pass 4 — Unified resource management

- Source/implementation comparison: `qa/manage-comparison.png` places the selected Mission Control source and all four 1440×1024 management screens in one visual input. The management screens preserve the source's narrow global rail, dense middle list, large evidence/detail canvas, near-black layered surfaces, 1px dividers, compact typography, and semantic cyan/green/amber/red states.
- Focused comparison: `qa/manage-focused-comparison.png` compares the selected source and Models management at readable scale. Global rail proportions, top metadata bar, list selection anatomy, detail tabs, compact cards, outline icons, and status hierarchy remain consistent. No additional focused crop was needed because labels, spacing, icons, and borders are legible at this scale.
- Fonts and typography: passed. The system sans stack, compact 7–10px management metadata, 17–23px page/entity titles, optical weights, uppercase eyebrow tracking, wrapping, and truncation follow the existing prototype and selected source hierarchy.
- Spacing and layout rhythm: passed. At 1440×1024 the 150px Global rail, 166px Category rail, 282px Catalog, and flexible Detail preserve a dense desktop rhythm. `qa/manage-compact-1100.png` confirms the 140px/244px compact tracks, single-column relation cards, persistent breadcrumb/status/action, and no horizontal overflow at 1100×800.
- Colors and visual tokens: passed. Existing `--bg`, `--panel`, `--border`, `--cyan`, `--green`, `--amber`, and `--red` tokens are reused; no gradients, ungoverned shadows, or conflicting management palette were added.
- Image and asset quality: passed. The real MemStack logo and account avatar remain intact. All new management icons come from the installed Radix outline family; there are no emoji, handcrafted SVG, CSS illustrations, or placeholder raster assets.
- Copy and content: passed. Models expose runtime/fallback/budget language; Skills expose contract/tool/validation language; Plugins expose permission/install/update language; Agents expose model/memory/autonomy/dependency language. Shared labels stay consistent across categories.
- States and interactions: passed. Category and entity selection, tabs, search, status filters, model configuration edit/save, skill validation, plugin install/disable/update, agent pause/enable, governed draft modal, form validation, and create confirmation all work with realistic mock data.
- Accessibility: passed for prototype scope. Categories and tabs are semantic navigation, inputs have labels/placeholders, dialogs retain modal semantics, state labels supplement color, and all core actions are keyboard reachable.
- Comparison result: no actionable P0/P1/P2 findings were found in the first rendered management comparison, so no visual-fix iteration was required. The visible focus ring on the currently activated navigation control is intentional keyboard feedback and remains within the accessibility contract.

## Final review

- Layout and spacing: passed. The selected three-column anatomy, queue grouping, execution summary, three-card status row, artifact frame, review actions, and steering composer are present at the target viewport.
- Typography and color: passed. Dense sans-serif hierarchy, cyan active accents, green progress, amber approval state, and near-black layered surfaces follow the selected direction without gradients.
- Images and icons: passed. The product icon and generated account avatar are real assets; interface icons use one consistent Radix family.
- Interactions: passed. Work/Code switching, task selection, approval dialog, send-and-resume confirmation, code artifact tabs, pause/resume, source workspace, review actions, steering input, four-category management navigation, configuration tabs, search/filter, validation, plugin lifecycle, agent enablement, and governed draft creation are functional.
- Plan-first creation: passed. Describe, context selection, Work/Code selection, plan generation, loading state, human preview, inline edit, enable/disable, add-step, re-plan, approve, task insertion, and approved-plan execution states are functional.
- Accessibility: passed for prototype scope. Semantic buttons, dialog roles, labels, alternative text, keyboard-reachable controls, visible focus behavior, and non-color state text are present. No motion is required for comprehension.
- Viewport resilience: passed for the supported desktop range. 1440 × 1024 matches the design target; `qa/task-plan-review-1100.png` confirms the plan list, approval rail, and persistent CTA remain usable at 1100 × 800, while `qa/manage-compact-1100.png` confirms the management catalog and detail pane remain usable with no horizontal overflow. Mobile is intentionally outside this desktop-client prototype's support contract.
- Runtime quality: passed. Production build succeeds and browser console reports no warnings or errors.

Known intentional differences: the implementation uses the MemStack production brand asset, product-specific copy, and a condensed global metadata bar. These preserve the selected hierarchy while making the prototype directly applicable to the current product.

New-task comparison result: the three new full-screen states inherit the selected Mission Control shell's typography, spacing density, near-black surfaces, 1px borders, cyan active state, green completion state, amber approval semantics, and Radix icon family. The focused comparison confirms the form hierarchy and approval rail remain readable at 1440 × 1024. No new raster imagery was required; the existing real brand asset is reused.

### Pass 5 — Settings information architecture and internationalization

- Source visual truth: `qa/manage-models.png` and the selected Mission Control shell remain the visual target for density, tokens, typography, and resource-management anatomy.
- Implementation evidence: `qa/settings-general-zh.png`, `qa/settings-general-en-viewport.png`, and `qa/settings-models-zh-final.png` capture Settings → General and Settings → AI resources → Models at 1440×1024. `qa/settings-models-zh-final-1100.png` captures the compact desktop state at 1100×800.
- Implemented changes: removed the standalone Manage entry; added a Settings rail with Personal and AI resources groups; embedded the existing catalog/detail workspace under Settings; added `en` and `zh-CN` switching, document language updates, stable internal IDs, and versioned local persistence.
- Full-screen visual comparison: `qa/manage-models.png` and `qa/settings-models-zh-normalized.png` were reviewed in one visual input. The implementation preserves the narrow global rail, dense catalog, large evidence/detail canvas, near-black layered surfaces, 1px dividers, typography hierarchy, and cyan/green/amber status system while replacing the former management-category rail with a complete Settings information architecture.
- Focused visual comparison: `qa/settings-source-rail-focus-ffmpeg.png` and `qa/settings-implementation-rail-focus-ffmpeg.png` were reviewed together. Rail width, spacing cadence, active-state anatomy, icon family, governance note, and compact label hierarchy remain consistent. No actionable P0/P1/P2 visual issues were found.
- Navigation and interaction verification: passed. The global Manage entry is absent; Settings is the single entry point; Models, Skills, Plugins, and Agents each open their catalog/detail workspace; the agent pause/enable lifecycle works and was restored to enabled after testing.
- Internationalization verification: passed. English and Simplified Chinese switch immediately, persist across a full reload, update the document `lang`, and localize shell navigation, Settings, resource categories, management controls, statuses, model descriptions, fallback routing, and relationship labels.
- Viewport verification: passed. At 1100×800 the document and body widths both remain 1100px with no horizontal overflow; the compact Settings rail, 244px catalog, and flexible detail canvas remain usable.
- Runtime verification: passed. The refreshed in-app browser reports zero warnings and zero errors; the local production build completes successfully.

### Pass 6 — Provider-first LLM configuration

- Source visual truth: `qa/model-provider-audit-before.png` supplies the existing Settings shell, density, typography, color tokens, catalog/detail anatomy, icon family, and focus behavior. Product behavior is grounded in the upstream evidence recorded in `../../docs/product/desktop-agent-ui/04-llm-provider-ux-research.md`.
- Initial P1 finding — wrong configuration object: the source listed individual models and treated Provider as a model metadata field. It had no reusable Provider credential, authentication method, endpoint validation, model discovery, manual Model ID path, or workspace-wide workload routing.
- Fix: replaced the model catalog with a Provider catalog and separated Overview, Connection, Models, Routing, and Usage. Added OAuth/API key/environment secret/no-auth modes, encrypted-secret language, default/custom endpoint fields, advanced API mode/headers/timeout, connection verification, automatic discovery, enablement switches, manual Model ID, workload roles, and ordered fallbacks.
- Initial P1 finding — incomplete primary journey: “Edit config” could not complete an LLM connection. Fix: added a working three-step Add Provider flow — Choose provider → Authenticate and verify → Enable discovered models — with disabled progression until connection test and model selection succeed.
- Full-view comparison evidence: `qa/model-provider-audit-before.png` and `qa/model-provider-overview-final.png` were inspected together at 1440×1024. The revised design preserves the global and Settings rails, 282px catalog, large detail canvas, near-black surfaces, 1px dividers, compact system typography, cyan active states, green connection health, amber attention, red offline state, and Radix outline icon family. No actionable visual P0/P1/P2 drift remains.
- Focused comparison evidence: `qa/model-provider-before-detail.png` and `qa/model-provider-after-detail.png` were inspected together. The Provider identity, five concise tabs, health card, enabled-model list, and workload-routing panel retain the former detail hierarchy while making the configuration object and next actions explicit.
- Typography, spacing, colors, and assets: passed. Text sizes, optical weights, truncation, card rhythm, token mapping, borders, radii, and semantic status colors remain aligned with the source. No new raster assets, custom SVG, CSS illustration, gradient, or placeholder imagery were introduced; the existing brand assets and Radix icons remain intact.
- Copy and internationalization: passed. Provider, credential, endpoint, discovery, enablement, routing, fallback, verification, and wizard language is available in English and Simplified Chinese; model IDs and third-party brand names remain intentionally untranslated.
- Interaction verification: passed. Provider search/filter/selection, connection test success, OpenRouter manual Model ID, model enablement control, routing selectors and fallback editing, and the full Add Provider wizard were exercised with realistic mock data. The wizard successfully added Azure OpenAI with two discovered models and was reset by reload afterward.
- Viewport verification: passed. `qa/model-provider-routing-1100.png` confirms the 1100×800 compact layout with no horizontal overflow (`bodyWidth = docWidth = viewport = 1100`); the routing roles, fallback editor, persistent catalog, and top actions remain usable.
- Runtime verification: passed. The in-app browser reports zero warnings and zero errors. Production build succeeds after the provider-first refactor.

### Pass 7 — Authentication, workspace context, and independent Settings window

- Initial P1 finding — missing authentication boundary: the prototype opened directly into the mission-control shell and provided no validation, session restore, or sign-out flow. Fix: added a dedicated Login screen with Workspace SSO, email/password, password visibility, trusted-device preference, localized validation, loading feedback, local mock-session restore, and explicit sign out.
- Initial P1 finding — Settings replaced the task workspace: the previous Settings implementation occupied the full application canvas and broke spatial continuity. Fix: Settings now opens as a centered modal window with its own title bar, search, close action, scrolling content, and persistent left rail while the current workspace remains visibly preserved underneath.
- Initial P1 finding — invalid context model: Tenant and Project were not represented as a parent/child choice. Fix: Settings → Workspace now presents current context, Step 1 Tenant, Step 2 Project filtered by the selected Tenant, and one explicit Switch workspace boundary.
- Initial P2 finding — stale landing after context apply: the first implementation updated sidebar labels but retained the previous task detail. Fix: successful apply closes Settings and lands on the selected Project page so shell labels and content agree.
- Full-view comparison evidence: `qa/settings-fullpage-before-popup.png` and `qa/settings-popup-account.png` were inspected together. The popup preserves the selected dark Mission Control shell, compact typography, 1px borders, cyan active state, and governance rail while improving task-context continuity and focus hierarchy.
- Focused comparison evidence: `qa/settings-before-popup-focused.png` and `qa/settings-popup-focused.png` were inspected together. The rail rhythm, card anatomy, outline icon family, semantic states, and account content remain aligned; the new title bar and dimmed workspace make window ownership explicit.
- Login visual verification: `qa/login-screen.png` and `qa/login-screen-1100.png` confirm a clear SSO-first hierarchy, labeled email fallback, trusted-device control, product trust narrative, and no horizontal overflow at both supported viewports.
- Workspace visual verification: `qa/settings-popup-workspace.png` and `qa/settings-popup-workspace-1100.png` confirm the two-step selection, current/pending context, fixed apply boundary, readable cards, and accessible scrolling at 1440×1024 and 1100×800.
- Interaction verification: passed. Invalid email/short password error, email login, SSO login, trusted-session reload, profile menu, Account shortcut, Workspace shortcut, Tenant filtering, Project selection, context apply, settings dismissal, and sign out were exercised with realistic mock data.
- Accessibility verification: passed for prototype scope. The Settings window uses dialog semantics; inputs, password toggle, checkbox, close action, tenant/project cards, and sign-out actions are keyboard reachable and labeled; state is communicated with text in addition to color.
- Viewport verification: passed. At 1440×1024 and 1100×800, `bodyWidth = documentWidth = viewportWidth` and horizontal overflow is false. The primary Login and Switch workspace actions remain visible or reachable.
- Runtime verification: passed. A fresh browser reload after the final implementation produced zero new warning/error console entries, and the production build completes successfully.

final result: passed
