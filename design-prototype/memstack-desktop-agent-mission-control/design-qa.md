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

### Pass 8 — Workspace → Conversation tree and Workspace Overview

- Source visual truth: browser annotation evidence plus `qa/workspace-overview-before-tree.png` at 1325×1160.
- Implementation evidence: `qa/workspace-overview-tree-1325-final.png` at 1325×1160 and `qa/workspace-overview-tree-1100-final.png` at 1100×800.
- Implemented scope: replaced the Project list in the Global rail with a Project-scoped Workspace → Conversation tree; added independent expand/collapse, Workspace overview selection, Conversation-to-task navigation, backend-aligned Workspace identity, root goal, session attention, member/agent, Project knowledge, execution environment, recent session, and audit activity surfaces.
- Backend grounding: the UI model follows `Tenant → Project → Workspace → Conversation` and the source mapping recorded in `../../docs/product/desktop-agent-ui/05-workspace-conversation-ux-mapping.md`. Project memory/graph/storage are explicitly labeled Project-scoped.
- Full-view comparison: `qa/workspace-overview-before-tree.png` and `qa/workspace-overview-tree-1325-final.png` were inspected in one comparison input. The new screen preserves the source shell, near-black layered surfaces, 1px dividers, cyan primary state, green healthy state, amber attention state, compact system typography, and bottom mode/account controls while replacing the annotated Project list and generic empty summary with the requested data-rich Workspace experience.
- Focused tree comparison: `qa/workspace-tree-before-focus.png` and `qa/workspace-tree-after-focus.png` were inspected together. The implementation keeps the original rail's visual tokens and icon family while making hierarchy explicit through chevrons, connector rules, Workspace rows, Conversation metadata, and semantic status markers.
- Focused overview comparison: `qa/workspace-overview-before-focus.png` and `qa/workspace-overview-after-focus.png` were inspected together. Generic Running/Needs input/Ready cards are replaced by a root-goal contract, sessions requiring attention, members/agents, Project knowledge, execution environment, recent Conversations, and audit activity without changing the selected visual direction.
- Initial P2 finding — compact tree readability: an older 1100px media rule still compressed the Global rail to 142px, truncating Workspace and Conversation titles beyond useful recognition. Fix: aligned the compact Global rail to the specified 200px. Post-fix evidence: `qa/workspace-overview-tree-1100-final.png`; measured sidebar width is 200px and `bodyWidth = documentWidth = viewportWidth = 1100` with no horizontal overflow.
- Fonts and typography: passed. The same Inter/system sans stack, optical weights, 6.5–10px dense metadata, 12–15px goal hierarchy, uppercase eyebrow tracking, ellipsis behavior, and 28px Workspace title are retained. Workspace and Conversation labels remain readable at both viewports after the compact fix.
- Spacing and layout rhythm: passed. The 220px desktop / 200px compact rail supports the requested hierarchy; 10px card gaps, 7–17px padding, 8px radii, grid tracks, and vertical rhythm match the established prototype. The overview scrolls independently at 1100×800 and keeps header actions reachable.
- Colors and tokens: passed. Existing `--bg`, `--panel`, `--border`, `--cyan`, `--green`, `--amber`, and `--red` tokens are reused. No gradient or ungoverned elevation was introduced.
- Image and icon quality: passed. The real MemStack logo and account avatar remain intact. New interface icons use the existing Radix outline family; no emoji, handcrafted SVG, CSS illustration, or placeholder raster asset was added.
- Copy and content: passed. UI copy is available in English and Simplified Chinese. Workspace-specific content is grounded in backend fields for Workspace, Conversation, WorkspaceTask, execution session, members, agents, ProjectStats, HITL, and activity. Project knowledge is explicitly labeled shared by the Project.
- Interaction verification: passed. Workspace collapse/expand, Workspace overview selection, tree Conversation selection, Recent session selection, overview Configure → Settings → close, and task surface return were exercised. The interaction state remains coherent after a full reload.
- Accessibility: passed for prototype scope. Tree toggles, Workspace rows, Conversation rows, status labels, header actions, recent-session rows, and Settings dialog are semantic buttons/regions with accessible names; state text supplements color. Keyboard reachability is preserved by native controls.
- Runtime verification: passed. Fresh reload restored both the tree and Workspace overview, produced zero new warning/error console entries, and the production build succeeds.

### Pass 9 — Content-first Conversation detail

- Source visual truth: `qa/session-detail-task-before.png` records the previous tree-to-Task behavior and the selected Mission Control shell. Implementation evidence: `qa/session-detail-conversation-user-final.png` at the full desktop viewport and `qa/session-detail-conversation-1100.png` at 1100×800.
- Implemented scope: Conversation selection now opens the Conversation itself. The primary canvas contains user and Agent messages, workspace events, expandable tool-call groups, verification progress, HITL decision cards, and a persistent composer. The secondary rail links the Task, Run context, participants, and outputs, with an explicit handoff to the existing Task canvas.
- Backend grounding: the information model follows the history/event stream exposed by `routers/agent/messages.py`, Conversation identity from `routers/agent/conversations.py`, persisted HITL actions, workspace events, linked WorkspaceTask, execution-session state, participants, and artifact events. The detailed mapping is recorded in `../../docs/product/desktop-agent-ui/05-workspace-conversation-ux-mapping.md`.
- Full-view comparison: `qa/session-detail-task-before.png` and `qa/session-detail-conversation-user-final.png` were inspected together. The implementation retains the source shell, Workspace tree, header density, near-black surfaces, 1px borders, cyan running state, green completion, amber decision semantics, compact typography, and existing icon family while replacing the wrong primary object with a readable chronological content stream.
- Focused comparison: `qa/session-detail-task-before-focus.png` and `qa/session-detail-conversation-focus.png` were inspected together. Message authorship, timestamps, tool summaries, code evidence, verification state, and the composer remain legible without changing the selected visual direction.
- Layout and viewport: passed. The full view preserves a clear timeline-to-context hierarchy. At 1100×800 the Global rail remains 200px, the context rail remains 230px, and measured body/document/viewport widths are all 1100px with no horizontal overflow.
- Typography, spacing, colors, and assets: passed. The existing Inter/system stack, dense metadata scale, card rhythm, token palette, radii, and Radix outline icon family are reused. No gradient, handcrafted SVG, CSS illustration, placeholder raster asset, or new dependency was introduced.
- Interaction verification: passed. Tool-call collapse/expand, sending a follow-up message and receiving mock acknowledgement, opening and returning from the linked Task canvas, selecting an input-blocked Conversation, and launching/closing its HITL review request were exercised.
- Accessibility and internationalization: passed for prototype scope. The timeline, messages, tool groups, composer, context rail, status text, and handoff controls use semantic native controls or labeled regions. New interface strings are available in English and Simplified Chinese; model IDs, code, paths, and authored message content remain intentionally untranslated.
- Runtime verification: passed. A fresh browser reload followed by Conversation selection restored the complete content view and produced zero warning/error console entries. The production build succeeds.
- Comparison result: the first rendered Conversation comparison found no actionable P0/P1/P2 visual defect; no corrective visual iteration was required.

### Pass 10 — Codex/Copilot-informed Session workspace redesign

- Research source of truth: official Codex App behavior and current ChatGPT desktop app mock captured in `qa/reference-codex-app-session-focused.png`; official GitHub Copilot App session/canvas captured in `qa/reference-copilot-app-session.png`. Product findings and observed-vs-inferred distinctions are recorded in `../../docs/product/desktop-agent-ui/06-session-detail-competitive-research.md`.
- Implementation evidence: `qa/session-detail-redesign-1565-final.png` at 1567×1164 and `qa/session-detail-redesign-1100-final.png` at 1100×800. The former `qa/session-detail-conversation-user-final.png` remains the before-state evidence.
- Implemented scope: replaced the transcript-plus-passive-context-rail model with Session Header + Narrative Thread + mode-aware Work Canvas. Code sessions provide Overview, Plan, Changes, Terminal, and Checks; Work sessions provide Overview, Plan, Artifact, Sources, and Verify. Task/Run metadata moved to Header or Overview.
- Full-view comparison: the two official references and `qa/session-detail-redesign-1565.png` were opened in one comparison input. The implementation adopts Codex's thread-plus-review-context relationship and Copilot's conversation-plus-canvas relationship while preserving MemStack's existing dark shell, Workspace tree, semantic status colors, density, and navigation tokens.
- Focused comparison: `qa/reference-codex-session-canvas-focus.png`, `qa/reference-copilot-session-canvas-focus.png`, and `qa/session-detail-redesign-focus.png` were opened together. The implementation visibly preserves the shared competitive anatomy: compact narrative on the left, persistent Composer, structured working surface on the right, familiar Diff, direct evidence access, and a continuous session boundary.
- Initial P2 finding — central workspace readability: the first implementation reused the prototype's smallest metadata size too broadly, leaving the Narrative Thread and Diff text harder to scan than the competitive references at 1100px. Fix: increased primary message, tool-group, canvas-tab, stage, Composer, and Diff typography while preserving the compact shell. Post-fix evidence: `qa/session-detail-redesign-1100-final.png`; no horizontal overflow was introduced.
- Information architecture: passed. Intent/explanation stay in the Thread; Plan, Changes/Artifact, Terminal/Sources, and Checks/Verify stay in the Canvas; HITL appears as a current-stage banner; Task handoff remains explicit.
- Interaction verification: passed. Grouped tool activity expands/collapses; all Code Canvas tabs switch independently; Diff-line click adds a structured reference chip; the reference is sent with Steering and receives an Agent acknowledgement; Terminal verification reruns and returns to passed; input-blocked sessions open the HITL review dialog; Work sessions expose Artifact and Sources canvases.
- Responsive verification: passed. At 1100×800 the Global rail is 200px, Narrative Thread is 355px, Work Canvas is 545px, and `bodyWidth = documentWidth = viewportWidth = 1100` with no horizontal overflow. Header metadata collapses by priority while Canvas tabs, Composer, and primary actions remain available.
- Fonts and typography: passed after the P2 fix. The existing Inter/system sans and Menlo code stack are retained with clearer optical hierarchy between shell metadata, authored messages, tool summaries, Canvas navigation, and Diff content.
- Spacing and layout rhythm: passed. The 40/60 Thread/Canvas relationship, 39px local navigation bars, 6–7px radii, 1px separators, compact card rhythm, and fixed Composer align with the selected desktop-native direction.
- Colors and tokens: passed. Existing near-black surfaces, cyan active state, green completion, amber approval, and red/green Diff semantics are reused without gradients or ungoverned elevation.
- Images and icons: passed. Existing MemStack logo and account avatar remain real assets; new UI controls use the existing Radix outline family. No handcrafted SVG, CSS illustration, emoji, placeholder raster, or approximate code asset was introduced.
- Copy and content: passed. Interface strings are localized in English and Simplified Chinese. Code, paths, model IDs, authored prompts, and runtime output remain intentionally untranslated. Research claims are separated from product-design inference in the competitive research document.
- Accessibility: passed for prototype scope. Canvas tabs, grouped activity, Diff lines, context chips, HITL, Composer, rerun control, and Task handoff are semantic native controls with accessible names; stage and status text supplement color. The visible focus ring remains intentional keyboard feedback.
- Runtime verification: passed. A fresh reload followed by Conversation selection restored Thread, Canvas, and Changes with zero new warning/error console entries. `git diff --check` and the production Vite build succeed.

### Pass 11 — Codex-aligned thread-centric shell

- Direction: realign the shell with the Codex app interaction model — thread as the primary workspace, composer-first task creation, inline Plan and HITL approval cards, and an inbox-style My Work — while preserving MemStack's Work/Code dual modes and existing dark Mission Control tokens.
- Implementation evidence: `qa/codex-01-home-composer-{1440,1100}.png`, `qa/codex-02-my-work-inbox-{1440,1100}.png`, `qa/codex-03-inline-approval-{1440,1100}.png`, `qa/codex-04-approval-resolved-{1440,1100}.png`, `qa/codex-05-plan-card-{1440,1100}.png`, and `qa/codex-06-thread-running-{1440,1100}.png` at 1440×1024 and 1100×800.
- Implemented scope: sidebar rebuilt as a Workspace-grouped thread list with inline status (amber Needs input pulse, cyan Running pulse, green Ready check) and relative timestamps; primary navigation reduced to My Work and Search; Home merged into a composer-first New thread page with Mode / Model / Reasoning effort / Permission mode selectors; the overlay plan wizard replaced by an inline thread Plan card with editable/toggleable steps, live effort recompute, Approve plan, and Ask agent to revise; the HITL modal replaced by a sticky inline approval card (Allow once / Always allow / Deny with scope) whose resolution lands in the timeline as a system event; My Work rebuilt as a cross-mode inbox grouped by Needs input / Running / Ready to review, with cards jumping straight into the owning thread; thread header aligned to Codex breadcrumbs (Project → Workspace → Thread) with mode badge, branch/workspace context, model badge, Share, and Archive.
- Interaction verification: passed. Sidebar thread selection opens the thread directly; inbox cards navigate to their owning thread (including a regression fix where cross-project fixture tasks without a thread location broke navigation); composer submission creates a thread and inserts a generating-then-ready Plan card; plan approval transitions the thread to Running; approval resolution appends a timeline system event and restores Running state.
- Responsive verification: passed at 1440×1024 and 1100×800 with no horizontal overflow; sidebar, thread, and Work Canvas preserve the approved density.
- Internationalization: passed. All new shell, composer, Plan card, approval card, and inbox strings are localized in English and Simplified Chinese; QA capture ran with locale `en` and all six views render fully in English.
- Colors and tokens: passed. Existing near-black surfaces, cyan active, green complete, amber approval, and red danger semantics are reused; no gradients or new palettes introduced.
- Accessibility: passed for prototype scope. Thread rows, inbox cards, plan step controls, and approval actions are semantic native controls with accessible names; status text supplements color.
- Runtime verification: passed. Automated capture across both viewports completed with zero console errors; the production Vite build succeeds.

final result: passed

## Pass 12 — Codex-aligned message anatomy (2026-07-20)

Scope: redesigned the thread message anatomy in `ConversationDetail.jsx` / `ConversationDetail.css` to match the Codex app conversation model: user messages are plain gray rounded bubbles with no avatar, name, header, or timestamp; agent replies are plain markdown-style text on the background with bold lead-ins and real bullet lists; tool executions are flat timeline rows (icon + past-tense verb + detail + right-aligned result/time) inside an expandable worklog group with a trailing chevron, a thinking row (sparkle, italic muted), edit rows with colored +N/−N diff counts, a terminal row with a mono prompt, and a running row with a spinner plus a cyan "Worked for {duration}" elapsed label; system and resolution events are slim muted inline rows.

- Visual design: passed. No bubbles/avatars/headers on agent messages; diff counts use green/red semantics; the running row uses the cyan token; no new palettes or gradients; both compact and readable type scales updated.
- Interactions: passed. Worklog group expands/collapses via a single header row with aria-expanded; approval resolution still appends a timeline event and dismisses the inline card.
- Accessibility: passed for prototype scope. Native buttons, aria-expanded on the worklog toggle, decorative spinner marked aria-hidden.
- i18n: passed. All new literals wrapped in t() with zh-CN translations; verified zh-CN thread rendering has no untranslated natural-language strings (file paths and commands intentionally stay as-is).
- Runtime verification: passed. QA screenshots codex-03/04/06 re-captured at 1440x1024 and 1100x800 with zero console errors; production build succeeds.

final result: passed
