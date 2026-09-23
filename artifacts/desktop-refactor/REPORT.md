# Desktop refactor — phase reports

Phase 1 report: see `P1-REPORT.md` (palette + tokens, kept as its own file).

# Phase 2 — Sidebar information architecture + anatomy

Date: 2026-09 (prototype mission-control refactor, phase 2 of N)
Target: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
(`src/components/Sidebar.jsx` + `src/styles.css` sidebar sections)
Scope: `agi-stack/apps/desktop` sidebar TSX/CSS + tokens + one QA fixture + one App.tsx wiring block.
No behavior removed; collapse (44px rail) and resize (180–420) untouched.

## Changes per file

| File | Change |
|---|---|
| `src/styles/tokens.css` | 5 new tokens in BOTH `:root` (dark) and `:root[data-theme='light']` blocks (key parity preserved): `--desktop-nav-hover-bg` `#111822`/`#e4e4e4`, `--desktop-nav-active-bg` `#17212d`/`#dcdcdc`, `--desktop-nav-badge-bg` `#203242`/`#d9d9d9`, `--desktop-new-thread-bg` `#11313e`/`#e8e8e8`, `--desktop-new-thread-text` `#dff8ff`/`#262626`. New-thread border reuses existing `--desktop-border-cyan-9` (`#267e96`). Hex budget stays 0 — all values live in token definitions. |
| `src/features/navigation/DesktopSidebar.tsx` | (1) Brand row is now a `<button>` → `onNavigate('home')`, with icon (30px, radius 8) + "MemStack" + `nav.agentWorkspace` subtitle (existing i18n key, both locales). (2) New Task button moved out of `.desktop-design-header` to directly below the brand (prototype order: brand → New thread → nav); behavior unchanged (still opens NewTaskFlow via `onNewTask`, same `overview.newTask` label = "New thread"). (3) New Search item between My Work and Activity via new optional prop `onOpenSearch?: () => void` — rendered standalone (NOT in `primaryItems`, NOT routed through `onNavigate`) because `navigation-contract.test.mjs` pins search out of the workbench-section model. (4) Feature-directory grid button moved from primary nav into the footer toolbar as an icon button (`desktop-design-toolbar-button`, `aria-haspopup="dialog"`, focus-restoring `event.currentTarget` trigger contract preserved; `featureDirectory.open` still appears exactly once). |
| `src/features/navigation/DesktopSidebar.css` | Grid rows 5 → 6 (`auto auto auto auto minmax(0,1fr) auto`). New-thread button pinned to prototype anatomy: height 34px, border `var(--desktop-border-cyan-9)`, bg `var(--desktop-new-thread-bg)`, text `var(--desktop-new-thread-text)`, radius 7px, 11px/700, hover = cyan border (disabled state kept). Nav items: min-height 32px, radius 6px, 11px text, 14px icons; hover `var(--desktop-nav-hover-bg)`; active `var(--desktop-nav-active-bg)` + 2px cyan left bar via `::before` (`left: -3px`, height 15px). Count badge: `var(--desktop-nav-badge-bg)` bg / `var(--desktop-cyan)` text, radius 8px, padding 1px 5px (was pill + rgba tint). Eyebrow (`.desktop-design-header-row`): color `var(--desktop-gray-3)` `#607083`, letter-spacing .12em (8px/800/uppercase unchanged). Brand block restyled (hover fill, 13px name, 9px muted subtitle). |
| `src/features/workspace/WorkspaceDock.css` | Thread status dots (already 6px with correct green/cyan/amber mapping) gain the prototype pulse: `@keyframes desktop-thread-status-pulse`, `data-status='active'` pulses 2s (running ≈ cyan), `data-status='attention'` pulses 1.6s (input ≈ amber); `prefers-reduced-motion` disables both. |
| `src/App.tsx` | `projectSearchDestinationPath` derived from the same `routeDiscoveryEntries` the command palette uses (`deriveDesktopNavigationDiscoveryEntries`, route id `project-project-search` → `/tenant/:tenantId/project/:projectId/advanced-search`); sidebar prop `onOpenSearch` calls `desktopProductionRouteNavigation.openPath(projectSearchDestinationPath)` — the identical navigation API as the palette item. Prop is `undefined` (button hidden) when the route is unavailable/disabled. |
| `src/qa/MissionControlQa.tsx` | Fixture passes `onOpenSearch` and `onOpenFeatureDirectory` no-ops so the full sidebar anatomy renders in screenshots. |

## Mapping decisions

- **Footer Notifications ≈ existing Activity nav item.** The desktop product keeps its Activity inbox in the primary nav (bell icon + unread badge, `switchSection('activity')`), pinned by `desktop-shell-fidelity.test.mjs` ("sidebar bell opens the real Activity inbox"). Per the brief's judgment clause, no duplicate footer Notifications entry was added; the prototype's footer Notifications dot maps to the Activity unread badge.
- **Search has no active-section highlight.** Search is a V2 route surface, not a workbench section (`navigation-contract.test.mjs` forbids `search` in `primaryItems`/`onNavigate`); the underlying section stays active while the route is open. Reactive hash-driven active state deferred (needs a route-location subscription, not sidebar anatomy).
- **Eyebrow copy kept**: desktop shows "{project} / WORKSPACES" (existing `workspaceTree.workspaces`) vs prototype "{project} / Threads" — copy is out of scope for this phase (structure + anatomy only).
- **Profile row/popover** already matched (avatar, name, tenant · project subtitle, Account settings / Switch workspace / Sign out); left as-is.

## Scope review

`DesktopSidebar` is
consumed only by `src/plugins/DesktopSidebarSurfaceV2.tsx` (production seam, props typed via
`Omit<ComponentProps<typeof DesktopSidebar>, 'resizeHandle'>`) and three QA fixtures
(`MissionControlQa`, `WorkspaceExecutionQa`, `NoProjectEntryQa`). The new `onOpenSearch` prop is
optional, so all existing callers compile unchanged (verified by `tsc --noEmit`). No symbols renamed.

## Verification

- `tsc --noEmit`: clean.
- Focused sidebar/shell suites (`desktop-shell-fidelity`, `desktop-shell-layout`, `navigation-contract`,
  `desktop-sidebar-surface-v2-wiring`, `automation-client`, `workspace-create-dialog`,
  `workspace-overview-style`, `design-tokens`, `theme`) run as part of the full suite — all green.
- FULL `node tests/run.mjs` (=`pnpm test`): **4589 tests / 4586 pass / 0 fail / 3 skipped** — identical
  to the phase-1 baseline. Run twice (after wiring, then after brand change): identical both times.
- Visual: temporary vite server on 127.0.0.1:5199 (started and killed within the same shell; port
  verified free afterward). `artifacts/desktop-refactor/p2-screenshot.mjs` captured:
  - `p2-mission-control-1440.png` (1440x1024)
  - `p2-mission-control-1100.png` (1100x800)
  - `p2-mission-control-mywork-1440.png` (active-state anatomy check)
  No horizontal overflow at either width (`scrollWidth === clientWidth`); **zero console errors /
  pageerrors** on all three loads.

### Visual assessment vs `qa/codex-01-home-composer-1440.png`

- Order now matches top→bottom: brand (icon + MemStack + Agent Workspace subtitle) → cyan-tinted
  New thread button (34px, `#11313e`/`#267e96`/`#dff8ff`) → My Work (badge `#203242`/cyan) → Search →
  Activity → project eyebrow → workspace tree with 6px status dots (green/amber/cyan, running+input
  pulsing) → footer (feature-directory grid + settings gear + profile row).
- Active anatomy confirmed on the my-work shot: solid `#17212d` fill + 2px cyan left bar.
- Intentional deltas: Activity retained (real product capability, maps to prototype footer
  Notifications); eyebrow reads WORKSPACES not Threads (copy deferred); footer uses icon buttons for
  directory/settings (desktop convention) instead of full-width label rows; thread rows keep the
  desktop's date-meta layout rather than the prototype's meta-line format (tree row copy/layout is a
  later-phase decision).

## Deferred

- Search nav item active highlighting (needs reactive route-hash subscription).
- Prototype thread-row meta line (`worktree · 6 files`) vs desktop date meta — phase for the tree rows.
- Focus-ring muting (`#2e8ba5` + soft glow) still pending from phase 1 notes.

# Phase 3 — Home composer landing (NewThreadComposer)

Date: 2026-09 (prototype mission-control refactor, phase 3 of N)
Target: `design-prototype/memstack-desktop-agent-mission-control` (`src/components/NewThreadComposer.jsx`
+ `styles.css` `.new-thread-*` / picker-menu rules; oracle `qa/codex-01-home-composer-1440.png`)
Scope: `agi-stack/apps/desktop` composer TSX/CSS + shared composer menu CSS + QA fixture. No behavior
or prop-contract changes.

## Changes per file

| File | Change |
|---|---|
| `src/features/task/NewThreadComposer.css` | (1) Eyebrow tracking `.14em → .12em` (oracle). (2) Control-row single-line fit inside the 680px column: `.composer-pickers` gap 6→5px, `.mode-picker button` padding `0 10px → 0 9px`, `.picker-chip` padding `0 8px → 0 7px`, `.picker-chip > b` max-width 156→120px. (3) Recent-thread dots: 5px gray → 6px with the oracle status mapping — default/ready green (`--green-9`), `active`/`running`/`planning` cyan + 2s pulse, `input`/`needs_input`/`needs_approval` amber + 1.6s pulse; new `new-thread-status-pulse` keyframes + `prefers-reduced-motion` guard (mirrors the phase-2 workspace-tree pulse). |
| `src/features/task/NewThreadComposer.tsx` | Workspace `PickerMenu` gains the existing `hideLabel` prop (chip shows the workspace name only; `aria-label` still includes the label). DOM order unchanged: `[+ Add] [Work/Code] [Workspace] [Model] [Effort] [Permission] … [send]`. No prop/signature changes. |
| `src/features/chat/ComposerMenus.css` | `.picker-menu`/`.plus-menu` dropdown anatomy per oracle + brief: background `--desktop-surface-14` (#101720) → `--desktop-surface-12` (#0d131b), border `--desktop-border-15` (#2a3643) → `--desktop-border-17` (#2c3948); radius already 10px. Shared with the session composer — both surfaces now match the oracle dropdown. |
| `src/qa/MissionControlQa.tsx` | Fixture-only: capability modes redistributed (`policy` → work, `plan` → work) and a fifth `ready_review` work item (`digest`) added so the default work-filtered inbox renders the oracle distribution (1 needs-input / 1 running / 2 ready-review; the code-mode view keeps the `migration` item). Sidebar badge 4 → 5. No production code touched. |

## Behavior decisions

- **Default landing unchanged.** `App.tsx:768` keeps `useState<WorkbenchSection>('workspace')`. No test
  or contract pins the default section (grepped `tests/` for default/initial-section pins; the only
  `initialSection` is the Settings overlay's). Per the brief, the default was left as-is either way;
  switching the landing to the home composer remains a product decision for a later phase.
- **Workspace picker retained** in the control row (desktop-only capability: unbound threads and
  workspace switching; the prototype has no equivalent). Its visible label is hidden to reach the
  oracle's single-row anatomy; the header workspace pill above provides context.
- **Send button kept at 32px** (prototype CSS pins 32px; the brief's "28px" is approximate). Cyan
  border tint already matched (`--desktop-border-cyan-9` / `--desktop-surface-cyan-4`).
- **No separate Attach chip added** — file upload already lives inside `ComposerPlusMenu` (oracle's
  Attach chip maps to that capability).
- Wrap remains as the graceful fallback below the 680px column; at both QA viewports (1440/1100) the
  row is single-line.

# Phase 4 — My Work inbox

Target: `src/components/InboxView.jsx` + `styles.css` `.inbox-*`; oracle `qa/codex-02-my-work-inbox-1440.png`.
Scope: `src/features/my-work/MyWorkQueue.css` only (full restyle; TSX structure already matched the
oracle anatomy — icon + label + count group headers, card header/title/summary/footer rows).

## Changes per file

| File | Change |
|---|---|
| `src/features/my-work/MyWorkQueue.css` | Page padding `48px clamp(24px,5vw,76px) 64px → 30px clamp(22px,4vw,54px) 48px`; dropped the `max-width: 1120px` auto-centered column (oracle is full-width, padding-bound). Heading: eyebrow 9px/.15em → 8px/.13em, h1 30px/−.045em → 22px/−.03em, description 12px → 10px, margin-bottom 38px → 24px. Group header: icon 14px → 13px, h2 11px/.02em → 12px/−.01em, margin-bottom 11px → 10px. Grid: `repeat(2, minmax(0,365px))` gap 10px → `repeat(auto-fill, minmax(300px,1fr))` gap 9px (1180px media override removed — auto-fill handles narrowing; 900px heading stacking kept). Card: padding `12px 14px 10px → 12px 13px`, title pinned to 13px/600 (brief: 13px semibold), footer progress column 90px → 72px, progress bar radius 999px → 2px. State boxes lose the 1120px max-width to match the full-width layout. |

## Group mapping (unchanged, already aligned)

`myWorkModel.ts` already maps the four backend authority groups onto the oracle's three display
groups: `needs_input` + `needs_approval` → **Needs input** (amber), `running` → **Running** (cyan),
`ready_review` → **Ready review** (green), ordered input → running → ready. i18n keys and labels
untouched — `myWork.displayGroup.ready_review` stays "Ready review" (pinned by
`my-work-mission-control.test.mjs`) vs the prototype's "Ready to review".

## Kept desktop extras (product capabilities / test pins)

Refresh action in the header; relative-time meta in the card header (oracle shows status meta);
completion outcome line on ready-review cards (`myWorkCompletionPresentation`); project name in the
card footer (pinned by the `/Project One/` assertion in `my-work-mission-control.test.mjs`); card
enter animation + hover lift (hover keeps the brief's border-cyan affordance).

## Scope review

`NewThreadComposer` is consumed by `src/plugins/DesktopNewThreadComposerSurfaceV2.tsx` and
the QA fixture; `MyWorkQueue` by `DesktopMyWorkQueueSurfaceV2.tsx` /
`DesktopRendererMyWorkQueueV2.tsx` / `desktopRendererAppCompositionV2.tsx` and the QA fixture. No
prop contracts changed (`hideLabel` is an existing prop applied at the composer's own call site), so
all callers compile unchanged (verified by `tsc --noEmit`). No symbols renamed.

## Verification (phases 3-4)

- `tsc --noEmit`: clean.
- Focused suites (`my-work-mission-control`, `navigation-contract`, `desktop-shell-fidelity`,
  `new-thread-workspace-selection`, `desktop-new-thread-composer-surface-v2-wiring`,
  `desktop-my-work-queue-surface-v2-wiring`, `workspace-overview-style`, `design-tokens`):
  **103 / 103 pass** standalone. (`theme` and `desktop-my-work-authority-module-v2` only run under
  the `tests/run.mjs` harness, which writes package aliases into the compiled dist; both are green in
  the full run.)
- FULL `pnpm test` (= `node tests/run.mjs`): **4589 tests / 4586 pass / 0 fail / 3 skipped** —
  identical to the phase-1/2 baseline.
- Visual: temporary vite server on 127.0.0.1:5199 (started and killed within the same shell; port
  verified free afterward). `artifacts/desktop-refactor/p3-screenshot.mjs` captured:
  - `p3-home-composer-1440.png` / `p3-home-composer-1100.png`
  - `p4-my-work-1440.png` / `p4-my-work-1100.png`
  - `p3-picker-menu-open.png` / `p3-plus-menu-open.png` (dropdown anatomy check)
  No horizontal overflow at either width (`scrollWidth === clientWidth`); **zero console errors /
  pageerrors** on all loads.

### Visual assessment vs oracles

- **P3 vs codex-01**: control bar is now a single row — `[+ Add] [Work|Code] [Desktop Client]
  [Model gpt-5.6-terra] [Effort Medium] [Ask for approval] … [→]`; eyebrow/h1/subtitle/workspace
  pill/composer card/suggestion cards/RECENT THREADS anatomy all match. Recent-thread dots now carry
  the oracle status colors + pulse. Remaining intentional deltas: the extra workspace chip and the
  labeled `+ Add` trigger (brief-required; the oracle render omits the plus trigger that the
  prototype JSX defines); recent-row meta lines show conversation summaries (desktop data) instead of
  `worktree · 6 files`.
- **P4 vs codex-02**: page padding, heading scale, group order/colors/counts, `auto-fill minmax(300px)`
  card grid, and card anatomy (status dot + mode icon + workspace / 13px semibold title / 2-line muted
  summary / 72px progress + phase label / arrow) all match. Intentional deltas: Refresh button,
  relative-time meta, the green completion outcome line on ready-review cards, and the pinned
  project-name footer slot. Fixture timestamps read "63 days ago" (fixed 2026-07 fixture dates).

## Deferred (phases 3-4)

- Default-landing switch from workspace overview to the home composer (documented above; unchanged).
- Focus-ring muting (`#2e8ba5` + soft glow) still pending from phase 1 notes.
- Picker/plus menu item typography stays on the desktop readability scale (11px labels vs the
  prototype's 10.5px) — global type-scale harmonization is a later-phase decision.

# Phase 5a — Session workspace header + context rail + layout modes

Date: 2026-09 (prototype mission-control refactor, phase 5a of N)
Target: `design-prototype/memstack-desktop-agent-mission-control`
(`src/components/ConversationDetail.jsx` + `ConversationDetail.css`; oracles
`qa/codex-06-thread-running-1440.png`, `qa/codex-03-inline-approval-1440.png`)
Scope: session header TSX/CSS, context rail TSX/CSS, right-sidebar width/layout wiring,
one test pin update, one QA harness extension, 4 new i18n keys (both locales).
CSS-first; all component/prop contracts unchanged (no new required props).

## Changes per file

| File | Change |
|---|---|
| `src/features/session/SessionWorkspace.tsx` | (1) Radix `<Badge>` replaced with the prototype StatusBadge pill: `.session-status-badge tone-<color>` with a 6px dot + label. (2) `statusColor` gains `'cyan'` for `active`/`running` (was green); `accepted`/`completed`/`ready_review` stay green, attention statuses stay amber, failures stay red — the three test-pinned mappings are preserved verbatim. (3) Stage strip: active stage now renders `ActivityLogIcon` (queued stays `ClockIcon`), and an `active` stage degrades to the amber `paused` class when status is `needs_input`/`needs_approval` (prototype "paused" state). (4) Header runtime chips gain a model chip (`modelLabel`, `DesktopIcon`) ahead of environment; the environment chip switches to `GlobeIcon` so the two chips are distinguishable. All action buttons (pause/resume/reattach/fork recovery dialog/open task/more menu) untouched. |
| `src/features/session/SessionWorkspace.css` | Header rhythm pinned to the prototype v2 scale: identity gap 6→7px, breadcrumb chevrons 9→12px, h1 17→18px. New `.session-status-badge` pill (10px, radius 10px, `color-mix` tints on `--cyan-9`/`--amber-9`/`--green-9`/`--red-9`; hex budget stays 0). Stage strip geometry: node min-width 72→76px, gap 6→7px, padding-right 13→16px, connector top 10→12px / width 10→13px, icons 13→14px, label 9→10px; new `.paused` amber state. Header buttons pinned to 32px / 10px (`.session-workspace-actions .rt-Button`; the ≤980px icon-only collapse still wins later in the file). More-menu trigger 28→32px. The pinned `grid-template-rows: 76px minmax(0, 1fr)` is unchanged. |
| `src/features/session/SessionContextRail.tsx` | Sections restructured to the prototype anatomy. RUN SNAPSHOT: eyebrow header + right-aligned status `em` (moved out of the rows), a 4px cyan progress bar with `n / 4` count driven by the stage index (ready/completed → 4/4 100%), and a `<dl>` of Current stage / Environment / Elapsed / Run mode / Permission (label muted left, value right). The old Status and Conversation rows were dropped (status lives in the header `em`; conversation mode stays in the thread pane label). WORK SURFACES: header gains the existing `session.workSurfacesDescription` helper note; buttons become icon + stacked title/subtitle + chevron rows, subtitles now use the existing `session.inspect*Description` keys (per-row record counts removed — counts remain on the canvas tab badges and in the evidence rows). LATEST EVIDENCE: green-check summary line (`session.linkedClaimCount` from `sourceCount` + `session.evidenceCoverage` subtitle) above the retained tool-activity/failed/sources rows. Success-tone attention card now leads with `CheckCircledIcon` instead of a green warning triangle. All `onOpenCanvas` wiring (`plan` / `changes`|`artifacts` / `checks`|`verification`) and approval actions unchanged. |
| `src/features/session/SessionContextRail.css` | Full rewrite to the flat prototype anatomy: card wrapper flattened (no bg/border/radius — class kept for the test pin), sections separated by hairlines (`padding: 13px 2px`), 8px/800/.1em uppercase eyebrows, progress bar (4px, `--cyan-9` fill on `--desktop-surface-14` track), facts `<dl>` (78px label column, 9px dt / 10px right-aligned dd), surface rows (grid 22px/1fr/12px, min-height 46px, 10px title / 8px subtitle, cyan hover), evidence summary (14px green check + 9px/8px text), denser evidence rows (26px, 10px). Attention card tightened to the prototype card (radius 8px, uppercase 8px eyebrow header). |
| `src/features/chrome/DesktopRightSidebar.tsx` | (1) Default panel width 280→248 (prototype context-rail width; min 220 / max 520 unchanged). (2) layout-focus mapping fixed: previously `focus` only widened the panel to the 520px cap, so the canvas could never take the body width. Now focus mode measures the live `.app-shell` grid (`gridTemplateColumns` first track = the user-resized left sidebar) and resizes the panel to `shell.clientWidth - sidebar - 40px activity bar`, collapsing the `minmax(0, 1fr)` thread column — the prototype's `layout-focus`. The width constraints passed to the hook and `ResizeHandle` lift `max` to 2000 only while focused; a window-`resize` listener re-pins the focused width; `split` still calls `panelWidth.reset()` (→ 248). Pure existing-state wiring: same `canvasLayout` state, same `panelWidth` hook, same storage key. Test-pinned patterns (`useState<'split' \| 'focus'>('split')`, `layout === 'focus') panelWidth.resize(`, `panelWidth.reset()`) preserved. |
| `src/i18n.tsx` | 4 new keys in BOTH locales: `session.currentStage` (Current stage / 当前阶段), `session.permission` (Permission / 权限), `session.linkedClaimCount` ({count} linked claims / {count} 条已关联引用), `session.evidenceCoverage` (Citation and source coverage / 引用与来源覆盖). Existing `session.workSurfacesDescription` + `session.inspect*Description` keys are newly referenced by the rail. |
| `tests/desktop-shell-fidelity.test.mjs` | One deliberate pin update ("prototype mission-control refactor 2026-09" comment): the run-mode row assertion moved from `<span>{t('session.runMode')}</span>` to `<dt>{t('session.runMode')}</dt>` (snapshot rows are now a `<dl>`). The `doesNotMatch` guard against a mislabeled `<span>{t('session.currentStage')}</span>` row is unchanged and still passes. |
| `src/qa/SessionRecoveryQa.tsx` + `sessionRecoveryQa.css` | Harness extension only (no new fixture): `?rail=1` mounts `SessionContextRail` in a 248px third column (224px below 1120px) mirroring the right-sidebar panel; `?status=running|needs_input|ready_review` overrides the fixture status/run-actions so the three oracle states can be captured. Default invocation (no params) is byte-identical in behavior — the fork-recovery dialog still auto-opens. |

## Wiring decisions

- **Work-surface buttons → canvas tabs**: the rail already routed through
  `onOpenCanvas(tab)` → `App.tsx handleOpenCanvas` (`setReviewTab(tab)` + open the canvas
  panel), which matches the prototype mapping (Plan→plan, Artifact→artifacts [work] /
  changes [code], Verify→verification [work] / checks [code]). No rewiring needed; only the
  row anatomy changed.
- **Prototype Share/Archive buttons** map to the desktop's existing more-menu items
  (rename/delete conversation) plus the canvas overview entry — no dead Share/Archive
  buttons were added since no backend capability exists for them here.
- **Attention card shows for every status presentation** (input/approval/failed/paused/
  disconnected/ready-review), not only `input` as in the prototype: it hosts the real
  approve / request-changes / review-canvas actions. Amber input tint matches codex-03.
- **Layout modes**: `layout-thread` = context panel at 248px (rail hidden behind the
  activity bar is the collapsed form); `layout-split` = canvas panel at the user's width
  (default 248); `layout-focus` = canvas expanded across the thread column via measured
  panel width. Documented in the `DesktopRightSidebar` docstring.

## Scope review

`SessionWorkspace` is consumed by `src/plugins/DesktopSessionWorkspaceSurfaceV2.tsx`
(pinned passthrough `<SessionWorkspace {...input} thread={thread} />`) and `SessionRecoveryQa`;
`SessionContextRail` by `DesktopRightSidebar.tsx` (pinned) and the QA harness;
`DesktopRightSidebar` by `src/plugins/DesktopRightSidebarSurfaceV2.tsx`. No prop contracts
changed, no symbols renamed; `tsc --noEmit` clean.

## Verification

- `tsc --noEmit`: clean (run after every edit batch).
- Focused suites (`desktop-shell-fidelity`, `desktop-shell-layout`,
  `desktop-right-sidebar-surface-v2-wiring`, `desktop-session-workspace-surface-v2-wiring`,
  `desktop-session-canvas-surface-v2-wiring`, `session-view-model`, `desktop-a11y-i18n`):
  **100 / 100 pass** standalone.
- FULL `pnpm test` (= `node tests/run.mjs`): **4589 tests / 4586 pass / 0 fail / 3 skipped**,
  run twice (after the main edits and after the final attention-icon tweak) — identical to
  the phase 1-4 baseline both times.
- Visual: temporary vite server on 127.0.0.1:5199 (started and killed within the same
  shell; port verified free afterward). `p5a-screenshot.mjs` (+ `p5a-reshoot-ready.mjs`)
  captured:
  - `p5a-session-running-1440.png` / `p5a-session-running-1100.png` (vs codex-06)
  - `p5a-session-needs-input-1440.png` (vs codex-03)
  - `p5a-session-ready-review-1440.png` (4/4 progress + green pill)
  - `p5a-session-recovery-default-1440.png` (default fixture regression: dialog auto-opens)
  No horizontal overflow at any viewport (`scrollWidth === clientWidth`); **zero console
  errors / pageerrors** on all loads.

### Visual assessment vs oracles

- **vs codex-06 (running)**: header anatomy matches — muted 10px breadcrumb with chevrons,
  truncating 18px title, cyan Running pill with dot, 4-stage connected strip (green checks,
  cyan active Verify with activity icon, muted queued Review, 13px connectors), compact
  model/environment/branch/elapsed chips, 32px actions. Rail matches: RUN SNAPSHOT eyebrow +
  cyan state em, 4px cyan progress bar at 75% with "3 / 4", dl rows (Current stage /
  Environment / Elapsed / Run mode / Permission), WORK SURFACES with right-aligned helper
  note and icon/title/subtitle/chevron rows, LATEST EVIDENCE green check + linked-claims
  summary + retained count rows.
- **vs codex-03 (needs input)**: amber Needs-input pill, Verify stage drops to the amber
  paused state, amber attention card atop the rail (uppercase eyebrow + description +
  review action), amber status banner in the thread column.
- **1100px**: stage strip and runtime chips hide per the existing ≤1280px media query
  (prototype does the same), rail narrows to 224px, title untruncates, no overflow.
- Intentional deltas: the rail keeps the desktop's right-sidebar panel header + 40px
  activity bar (per the brief); run mode stays as a fourth dl row (test-pinned truthful
  labeling); the fixture's "0 linked claims" reflects its zero-source data; header chips
  ellipsize aggressively at the QA width because the fixture branch label is long.

## Gaps / deferred

- No QA harness mounts the full `DesktopRightSidebar` (activity bar + resizable panel +
  canvas focus mode); the rail was verified through the extended `SessionRecoveryQa`
  column instead. The focus-mode width math is therefore verified by types/tests/source
  pins only, not by a screenshot — a full right-sidebar harness is a candidate for phase 5b.
- Chat panel / thread column internals (composer, messages, inline approval card) are
  phase 5b by scope.
- Ready-review stage strip still shows Verify active because the fixture's `stage` is
  `verify` — stage comes from projection data, not from status; no presentation bug.
- Focus-ring muting (`#2e8ba5` + soft glow) still pending from phase 1 notes.

---

# Phase 5b — Session chat: thread anatomy, worklog, approval card, steering composer

Scope: restyle the session chat surface (`session-chat-narrative`) to the prototype
message anatomy (`ConversationDetail.jsx/.css`; oracles codex-06 thread-running,
codex-03 inline-approval, codex-04 approval-resolved). CSS-first; DOM and every
test-pinned class name unchanged; no new behavior.

## Changes per file

- `src/styles/tokens.css` — new 18-token `--desktop-approval-*` family in BOTH
  `:root` (dark, prototype-exact: border `#6b5426`, bg `#171208`, icon chip
  `#7a5f2b`/`#241a09`, eyebrow `#a08a56`, title `#f0e3c4`, text `#a3906a`, scope
  box `#3d3117`/`#100c05`/`#b3a072`, field `#0d0a04`/`#e8dcbd`/`#6d5f41`, actions
  `#1b1509`/`#c9b787`, primary `#8a6d2c`/`#6b5316`/`#fff3d6`) and the light block
  (warm light equivalents). Token parity enforced by `theme.test.mjs`; hex budget
  stays 0 outside tokens (`design-tokens.test.mjs`).
- `src/features/chat/ChatPanel.css`
  - Message anatomy: user surface `padding 12px 14px`, 1px `--desktop-bubble-user-border`,
    12px radius, `--desktop-bubble-user-bg`, no shadow, max-width 84%; agent surface
    fully flat (`padding/border/radius 0`, transparent, no shadow), article max-width
    100%; base chat text 12px/1.66 (was 14px/1.5). Narrative-scoped hides:
    `.session-thread-avatar` and `.session-message-identity` `display: none`
    (base avatar rule keeps its test-pinned `display: grid`); `.transcript-meta`
    becomes an absolute floating action-menu anchor (user messages: left of the
    bubble, vertically centered). Base rules stay token-driven for other hosts.
  - Worklog: group header 11px/600 label + 9px meta; running status em amber→cyan
    (prototype "Worked for" vocabulary); items padding-left 27px. Tool-call rows
    flatten to the prototype session-worklog row — no execution-card chrome
    (border/background/shadow removed, 6px-radius hover tint), 18px bare status
    icon (28px chip gone), title 10.5px/600, summary 9.5px, meta 9px, details
    indent 26px, row grid `18px 1fr auto`. Thought cards inside the worklog
    collapse to slim rows (18px icon, transparent surface, 30px toggle).
  - HITL amber card: `.message.timeline-row:has(.hitl-response-card)` gets the
    approval frame (1px approval border, 10px radius, approval bg, 13px 14px
    padding); 30px icon chip; "Human input" title as the HUMAN-DECISION eyebrow
    (uppercase 8px/800/.12em, approval-eyebrow); summary/meta hidden; question
    12px/650 approval-title; meta 9px approval-text; evidence scope box on
    scope tokens; deny-feedback + Radix TextArea (root + input + placeholder) on
    field tokens; action trio — solid "Allow once" on primary tokens, soft
    "Always allow"/"Deny" on action tokens with a scope-tinted inset ring.
    Resolved (`is-answered`): card flattens to a slim row (no frame, 18px icon),
    only the `.timeline-hitl-response` chip stays — green flex pill, `.is-denied`
    red.
  - Composer: `.send-pill` gains the prototype cyan ring
    (`inset 0 0 0 1px var(--desktop-border-cyan-9)`); control radius stays the
    test-pinned `var(--session-composer-control-radius)`.
- `src/features/chat/HitlResponseCard.tsx` — root gains
  `hitl-response-card` + `is-answered` modifiers; `.timeline-hitl-response` gains
  `is-denied` when the response is `chat.response.denied`. Source pins
  (`hitlResponsePresentation(item, hitlType)`, `timeline-hitl-response` substring)
  preserved.
- `src/qa/SessionSteeringQa.tsx` — new fixture-only `?hitl-approval=1` mode: one
  pending `permission_asked` item plus its `DesktopApprovalRequest` (permission
  context: action/tool_name/risk_level/description/allow_remember) in
  `timelineState.approvalRequests`, `respondableHitlRequestIds` includes it, so the
  full amber card (scope evidence + enabled action trio) renders for the codex-03
  comparison. No production code path touched.

## Wiring decisions

- **Approval placement**: the prototype pins the approval card above the composer,
  but the desktop composer area has no actionable approval slot
  (`CurrentActivityHeadlineBar` is status-only). The card stays in the timeline
  (its existing, tested position) and takes the amber anatomy in place.
- **Delivery mode**: the `.composer-delivery-switch` segmented control
  (Steer now / Queue next, wired to `runInputDelivery`) already existed from the
  compose-ahead work — styling-only phase, no new control.
- **Assistant flat text** is done by swapping the narrative-scoped base surface
  rules plus hiding avatar/identity in the narrative scope only, so other hosts
  (SessionWorkspace timeline, etc.) keep their chrome and every CSS pin survives.
- Eyebrow text keeps the existing i18n string `chat.humanInput` ("Human input")
  instead of the prototype's "HUMAN DECISION" — the visual treatment (uppercase,
  tracked, eyebrow color) carries the anatomy; no new string introduced.

## Verification

- `npx tsc --noEmit` clean.
- Focused suites after each numbered change, then full `pnpm test`
  (= `node tests/run.mjs`): **4589 tests / 4586 pass / 0 fail / 3 skipped** —
  identical to the phase 1-5a baseline.
- Screenshots via `p5b-screenshot.mjs` (vite on :5199 inside the command chain,
  killed + port verified free afterward; console clean, no horizontal overflow at
  1440 or 1100):
  - `p5b-conversation-1440.png` / `p5b-conversation-1100.png` (vs codex-06)
  - `p5b-steering-1440.png` / `p5b-steering-1100.png`
  - `p5b-hitl-approval-1440.png` (vs codex-03)
  - `p5b-hitl-1440.png` (resolved slim rows, vs codex-04)
  - `p5b-compose-ahead-1440.png`

### Visual assessment vs oracles

- **vs codex-06 (thread running)**: user message is a right-aligned 12px-radius
  bubble with no avatar/name/timestamp; assistant replies are flat 12px/1.66 text
  with compact bullet rhythm; the tool group is a slim header ("3 tool calls" meta
  + chevron) with flat worklog rows; the running indicator keeps its spinner +
  cyan "worked for" em; the composer shows the steering textarea with the
  Steer now / Queue next segmented control and cyan-ringed send pill.
- **vs codex-03 (inline approval)**: the pending permission request renders the
  amber card — HUMAN INPUT eyebrow, 30px icon chip, warm title, scope evidence
  box (action/target/risk + reason), amber instruction field tokens, and the
  Deny / Always allow / Allow once trio with the solid amber primary.
- **vs codex-04 (approval resolved)**: answered requests collapse to slim rows —
  HUMAN INPUT eyebrow plus a green inline chip (ANSWER / DECISION / SAVED
  VARIABLES / PERMISSION RESPONSE / SELECTED ACTION); the denied variant is
  CSS-analogous red (`.is-denied`), not exercised by the fixture.
- Intentional deltas: approval card stays in the timeline (see Wiring decisions);
  eyebrow copy stays "Human input"; the action trio is left-aligned in the narrow
  thread column (prototype right-aligns in its wider column); code blocks keep
  their framed surface inside flat assistant text.

## Gaps / deferred

- The large empty region under the compose-ahead "Writing response" group is
  pre-existing fixture layout (identical in `p5b-before-compose-ahead-1440.png`).
- Light-theme approval tokens are defined with warm light equivalents but only
  the dark theme was screenshot-verified.
- The hover action menu repositioning (floating beside the bubble) is
  structure-verified by tests; hover-state pixels not captured.
- Full `DesktopRightSidebar` QA harness remains deferred from phase 5a.
- Focus-ring muting still pending from phase 1 notes.

---

# Phase 6 — Settings workbench window + login screen

Date: 2026-09 (prototype mission-control refactor, phase 6 of N)
Target: `design-prototype/memstack-desktop-agent-mission-control`
(`src/components/SettingsPopup.jsx` + `LoginScreen.jsx` + `styles.css`
settings/login sections; oracles `qa/settings-popup-models-1100.png`,
`qa/settings-popup-account.png`, `qa/model-provider-overview.png`,
`qa/manage-skills.png`, `qa/manage-agents.png`, `qa/login-screen.png`)
Scope: settings window + managed-resource/provider views + login screen
TSX/CSS, 4 new tokens, one QA screenshot script. No behavior or prop-contract
changes.

## Changes per file

| File | Change |
|---|---|
| `src/styles/tokens.css` | 4 new tokens in BOTH `:root` (dark) and `:root[data-theme='light']` blocks (key parity preserved): `--desktop-rail-active-bg` `#13232d`/`#dcdcdc`, `--desktop-rail-active-border` `#285467`/`#c2c2c2`, `--desktop-rail-badge-active-bg` `#173544`/`#d5d5d5`, `--desktop-pill-neutral-border` `#374352`/`#c6c6c6`. Hex budget stays 0 — `design-tokens.test.mjs` (incl. the migrated-hex ban list, `#285467` is on it) and `theme.test.mjs` parity both green. |
| `src/features/settings/SettingsWindow.css` | Rail: group-label color → `var(--desktop-gray-15)`; nav button grid pinned to `24px minmax(0,1fr) 18px` (icon / label / badge) plus a hover rule (bg `var(--desktop-surface-15)`, text `var(--desktop-gray-30)`); active item uses `--desktop-rail-active-bg` + `--desktop-rail-active-border`, its subtitle drops to `--desktop-gray-11`. Badge `em`: 17px chip, radius 8px, `--desktop-surface-29` bg / `--desktop-gray-6` text; active variant `--desktop-rail-badge-active-bg` bg / cyan text. Titlebar close button pinned to the prototype icon-button anatomy (bg `--desktop-surface-14`, border `--desktop-border`, radius 6px, hover border-strong + white). Scope card becomes grid `27px 1fr 14px` with a 26px avatar chip (`--desktop-surface-cyan` bg / `--desktop-border-cyan` border / cyan icon, radius 6px); the selector `.settings-window-scope > .settings-window-scope-avatar` is deliberately specific because an existing `.settings-window-scope span` rule would otherwise win. |
| `src/features/settings/SettingsWindow.tsx` | `CubeIcon` import; scope-card DOM is now avatar chip (CubeIcon) → text → `LockClosedIcon` last. No prop/signature changes. |
| `src/features/settings/ManagedResourceViews.css` + `.tsx` | `.managed-resource-status` pill: 7px font, neutral border `--desktop-pill-neutral-border`, active color `--desktop-green` (was green-vivid), attention `--desktop-amber` (was amber-dim) — the prototype manage-* pill anatomy. Overview label restructured: TSX now renders `<div className="managed-resource-overview-label"><span>{t('settings.overview')}</span></div>`; CSS is a 38px strip (`padding 0 20px`, 8px text) whose `span` is the active tab — white, relative, with a 2px cyan `::after` underline inset 8px. |
| `src/features/settings/ModelProviderWorkspace.css` | `.provider-status` → 7px + `--desktop-pill-neutral-border`; `.provider-tabs` 42→38px, tab button font 11→8px (prototype provider-overview tab strip). |
| `src/features/auth/LoginScreen.css` | Full prototype type scale applied to the existing login DOM: brand span 9px, eyebrows 8px, proof b/span 9/8px, story footer 8px, card header p 10px, mode toggle 10px, sso 10px, divider 8px, label 9px, inputs 10px, options 8px, error 8px, submit 10px, legal 7px, help 8px. Device dialog: eyebrow 8px, p 9px, code label 7px, code small 8px, status b/small 9/7px, error 8px, action buttons 8px. Existing pins preserved verbatim (`width: min(430px,100%)`, submit bg/border/hover tokens, `min-height: 720px` + the 719px media query). |

## Mapping decisions

- **Settings window kept as a window.** The desktop settings surface is a modal
  workbench window (`DesktopSettingsWindowSurfaceV2`) over the app; the
  prototype's full-page settings maps onto the same rail + catalog + detail
  anatomy inside that window. No windowing behavior changed.
- **Rail search retained** (prototype has a settings search affordance) and the
  desktop's extra sections (updates, notifications, keyboard shortcuts, browser
  integration) stay — product capabilities the prototype lacks.
- **Scope card** maps the prototype workspace switcher chip to the desktop's
  tenant/client lock indicator: avatar chip + name/subtitle + lock icon, no
  interactive switcher added (no such capability exists).
- **Overview tab styling** is generic in `ManagedResourceViews`, so every
  managed-resource section (models, MCP, skills, plugins, agents, sub-agents)
  inherits the same 38px strip + cyan-underline active tab — matching the
  prototype manage-* pages' top strip.
- **Login copy/locales unchanged** (zh fixture in screenshots); only the type
  scale moved. SSO device-auth dialog anatomy (eyebrow / code block / status /
  actions) was restyled to the prototype `LoginScreen.jsx` device-flow rules.

## Scope review

`SettingsWindow` is consumed by
`src/plugins/DesktopSettingsWindowSurfaceV2.tsx` and the QA fixture
`src/qa/ProviderSettingsQa.tsx`; `ManagedResourceViews` by `SettingsWindow`;
`ModelProviderWorkspace` by the settings window's model section; `LoginScreen`
by `App.tsx` and `src/qa/LoginSsoQa.tsx`. No prop contracts changed, no
symbols renamed; `tsc --noEmit` clean.

## Verification

- `npx tsc --noEmit`: clean.
- Focused suites standalone (`login-screen-fidelity`, `login-screen-model`,
  `settings-modal-behavior`, `settings-navigation-model`, `design-tokens`,
  `desktop-shell-fidelity`, `settings-entry-routing`, `native-oauth-login-wiring`,
  `workspace-settings-dialog`): **106 / 106 pass**.
- FULL `pnpm test` (= `node tests/run.mjs`): **4589 tests / 4586 pass / 0 fail /
  3 skipped**, re-run after all edits — identical to the phase 1-5b baseline.
- Visual: temporary vite server on 127.0.0.1:5199 (started and killed within
  the same shell; port verified free afterward).
  `artifacts/desktop-refactor/p6-screenshot.mjs` captured:
  - `p6-login-1440.png` / `p6-login-1100.png` (vs login-screen.png)
  - `p6-login-sso-1440.png` / `p6-login-sso-expired-1440.png` (device-auth
    dialog; expired shows the amber expired-code state)
  - `p6-settings-models-1440.png` / `p6-settings-models-1100.png` (vs
    settings-popup-models-1100 / model-provider-overview)
  - `p6-settings-account-1440.png` (vs settings-popup-account)
  - `p6-settings-skills-1440.png` (catalog error state in the new chrome —
    see Deferrals)
  - `p6-settings-agents-1440.png` (agents section fully populated in local
    mode; vs manage-skills / manage-agents managed-resource anatomy)
  - `p6-force-password-change-1440.png` (login regression: force-change card)
  - `p6-workspace-settings-1440.png` / `p6-workspace-create-1440.png`
    (workspace QA harness regression checks — not restyle targets)
  No horizontal overflow at any viewport (`scrollWidth === clientWidth`);
  **zero console errors / pageerrors** on all loads.

### Visual assessment vs oracles

- **vs login-screen.png**: two-panel anatomy matches — brand block (logo +
  MemStack + subtitle), story panel with eyebrow / display headline /
  description / three proof rows / footer, form panel with mode toggle,
  eyebrow + title + subtitle, SSO button with arrow, divider, work-email /
  password fields, keep-signed-in + forgot row, cyan submit with arrow, legal
  line, and the first-time help row — now on the prototype type scale
  (8–10px). 1100px render is clean with no wrap/overflow.
- **vs settings-popup-models-1100 / model-provider-overview**: rail anatomy
  matches — group eyebrows, 24px icon / label / 17px badge grid rows, cyan-
  bordered active item with tinted bg, titlebar search + icon-button close,
  scope card with avatar chip and lock. Models section matches the provider
  overview: 38px tab strip with 8px tabs, provider status pills at 7px with
  neutral borders, green ACTIVE / amber attention pills.
- **vs settings-popup-account**: account section renders correctly in the new
  chrome; rail group labels and badges match the oracle.
- **vs manage-skills / manage-agents**: the agents section (local mode, fully
  populated fixture) matches the managed-resource anatomy — 282px catalog,
  filter pills (7px), topbar with search + import/create actions, cyan-
  underlined overview tab, and the card grid. This is the visual evidence for
  the shared `ManagedResourceViews` pattern; the skills cloud-mode catalog
  shows its error state inside the same chrome (deferral below).
- **Intentional deltas**: settings stays a centered modal window rather than
  the prototype's full page; zh copy (fixture locale) vs the oracle's English;
  rail keeps the desktop's extra sections; login panel keeps its existing
  layout widths (only type scale was restyled).

## Gaps / deferred

- **Skills catalog cloud-mode fixture contract drift (pre-existing, fixture-only).**
  `provider-settings.html?mode=cloud&section=skills` fails with "desktop
  tenant skill definitions operation response invalid": the fixture
  system-scope skill `code-verification` in `src/qa/ProviderSettingsQa.tsx`
  (~line 218) lacks `tenant_id`, which `requireDesktopTenantSkillDefinitionV2`
  requires as a string for system skills. In local mode skills fail with
  `desktop_sidecar_launch_capability_required`. Pure data/contract drift, not
  caused by this phase's edits; many tests import that fixture, so it was NOT
  patched here. `p6-settings-skills-1440.png` shows the resulting error state
  rendering gracefully inside the new chrome. Fixing the fixture (or the
  contract) is a follow-up decision.
- Light-theme settings/login tokens are defined (parity-enforced) but only the
  dark theme was screenshot-verified, same as phase 5b.
- Picker/menu type-scale harmonization remains a later-phase decision (from
  phases 3-4 notes).
- Focus-ring muting (`#2e8ba5` + soft glow) still pending from phase 1 notes.

---

# Phase 7 — Work Canvas / review panel tab bar + tab content headers

Date: 2026-09 (prototype mission-control refactor, phase 7 of N — final surface phase)
Target: `design-prototype/memstack-desktop-agent-mission-control`
(`src/components/ConversationCanvas.jsx` + `ConversationDetail.css`
`.session-canvas-tabs` / `.session-plan-canvas` sections; oracles
`qa/reference-codex-session-canvas-focus.png`, `qa/codex-05-plan-card-1440.png`)
Scope: review-panel tab bar CSS, plan review card palette (CSS only), 4 new
tokens. No TSX, prop-contract, i18n, or model changes.

## Changes per file

| File | Change |
|---|---|
| `src/styles/tokens.css` | 4 new tokens in BOTH `:root` (dark) and `:root[data-theme='light']` blocks (key parity preserved): `--desktop-plan-card-border` `#28465a`/`#c2c2c2`, `--desktop-plan-card-bg` `#0d1520`/`#f3f3f3`, `--desktop-plan-icon-bg` `#102b35`/`#e8e8e8`, `--desktop-plan-icon-border` `#2b6d82`/`#bdbdbd` — lifted verbatim from the prototype plan card (dark) with neutral grayscale light counterparts. Hex budget stays 0 (custom-property definitions are exempt; `design-tokens.test.mjs` 5/5 green). |
| `src/app-shell.css` | `.review-tabs` / `.review-tab` / `.review-tab-actions` min-height 40 → 44px (prototype 48px strip, kept compact). `.review-tab`: padding `0 11px → 0 12px`, font-size 12 → 11px, inactive color `--desktop-muted` → `--desktop-faint` (prototype `#5d6b7e`). Hover/selected split: hover keeps the faint slate tint; selected drops the background fill and is now full-opacity `--desktop-text` + the existing 2px cyan `border-bottom` underline (same vocabulary as the phase-6 management tabs). `.review-tab em` count badge becomes a small neutral chip (padding 1px 6px, radius 7px, bg `--desktop-nav-badge-bg`, color `--desktop-muted`, 10px) — the prototype `em` badge anatomy (`#1a2430` chip). The ≤1320px media query that hides badges stays. |
| `src/features/session/SessionPlanReview.css` | Plan card palette applied: `.session-plan-approval-card` border → `--desktop-plan-card-border`, radius 9 → 10px, background rgba cyan tint → `--desktop-plan-card-bg`; header icon tile border → `--desktop-plan-icon-border`, bg → `--desktop-plan-icon-bg`, radius 7 → 8px. `.session-plan-task-list li` step rows take the same card palette (border `--desktop-plan-card-border`, bg `--desktop-plan-card-bg`, radius 8 → 10px) so the whole plan review reads as the prototype plan card. |
| `src/features/task/NewTaskPlanReview.css` | Card anatomy only (brief-named file): `.new-task-plan-objective` and `.new-task-plan-step` borders → `--desktop-plan-card-border`, radius 6 → 10px, bg → `--desktop-plan-card-bg`; objective icon tile → `--desktop-plan-icon-border` / `--desktop-plan-icon-bg`, radius 6 → 8px. The `new-task-flow-fidelity` pin (`.new-task-plan-step` min-height 74px + grid columns) is preserved verbatim. |

## Mapping decisions

- **Count badges already existed in the model** — `WorkspaceReviewPanel.tabValue()`
  computes per-tab values (changes diff stats, activity/artifacts/apps/agents/
  graph/insights counts, checks failed-count or record count, sources count)
  and renders them as `<em>`. No data invented; only the chip styling was added.
- **Tab labels unchanged.** Existing i18n keys already carry near-prototype
  wording (`Overview/Plan/Changes/Terminal/Checks/Artifacts/Sources/
  Verification`); the deltas (`Artifacts` vs `Artifact`, `Verification` vs
  `Verify`) live in both translation dictionaries, so per the brief's no-churn
  clause they were left as-is. `Activity`/`Apps` (and the conditional
  `Context`/`Runtime`/`Graph`/`Insights`/`Agents`) remain as the desktop
  superset, visually consistent via the shared `.review-tab` anatomy.
- **Tab order unchanged** — it is model-driven in `sessionCanvasTabs(mode)`
  (`sessionCanvasModel.ts`) and the code-mode order already matches the
  prototype exactly (overview, plan, changes, terminal, checks). Work mode
  keeps the extra desktop `changes` tab between `plan` and `artifacts`;
  reordering would churn a tested model for zero visual gain (documented, not
  done).
- **Layout toggle + close on the right already existed** (`.review-tab-actions`
  with focus/split + close IconButtons, gated by
  `workspaceReviewPanelChrome(Boolean(sessionControls))`) — only the strip
  height moved with the tab bar.
- **Plan tab content** uses the desktop's own plan review (`SessionPlanReview`
  — approval fields + atomic approve action are real capabilities the
  prototype card lacks); per the brief only the card anatomy/palette moved,
  not the structure (no add-step/inline-edit in this surface — those live in
  the New Task flow plan review, which got the same palette).

## Verification

- `npx tsc --noEmit`: clean.
- Focused suites standalone (`design-tokens` 5/5, `desktop-shell-fidelity`
  51/51, `new-task-flow-fidelity` 6/6, `session-view-model` 15/15,
  `run-completion-summary-model` 11/11, `desktop-session-canvas-surface-v2-wiring`
  3/3, `desktop-shell-layout` 16/16): **102 / 102 pass**. (`theme` only runs
  under the `tests/run.mjs` harness — green in the full run.)
- FULL `pnpm test` (= `node tests/run.mjs`): **4589 tests / 4586 pass / 0 fail /
  3 skipped** — identical to the phase 1-6 baseline.
- Visual: temporary vite server on 127.0.0.1:5199 (started and killed within
  the same shell; port verified free afterward).
  `artifacts/desktop-refactor/p7-screenshot.mjs` captured:
  - `p7-plan-review-1440.png` / `p7-plan-review-1100.png` (vs codex-05)
  - `p7-plan-review-approved-1440.png` (approved-state regression)
  - `p7-evidence-1440.png` / `p7-evidence-checks-1440.png` / `p7-evidence-1100.png`
    (tab bar with count-badge chips, sources + checks views)
  - `p7-artifact-preview-1440.png` / `p7-artifact-preview-1100.png` (regression)
  No horizontal overflow at any viewport (`scrollWidth === clientWidth`);
  **zero console errors / pageerrors** on all loads.

### Visual assessment vs oracles

- **vs reference-codex-session-canvas-focus / codex-05 tab strip**: the canvas
  tab bar now reads as the prototype strip — compact 44px row, muted inactive
  tabs, active tab = full-opacity text + 2px cyan underline, count badges as
  small neutral chips (`Artifacts 2 · Sources 2 · Checks 3` in the evidence
  fixture, `versioned_atomic · v7` chip in the plan fixture). At 1100px the
  badges hide per the existing ≤1320px media query (the prototype likewise
  compacts its tabs at narrow widths).
- **vs codex-05 (plan card)**: the plan review surface now carries the
  prototype palette — step rows and the approval card on `#0d1520` /
  `#28465a` / 10px radius, the rocket icon tile on `#102b35` / `#2b6d82`.
  The approved state renders the retained green note inside the same rhythm.
- Intentional deltas: zh copy (fixture locale) vs the oracle's English;
  desktop keeps its extra tabs (activity, apps, and conditional
  context/runtime/graph/insights/agents); tab labels keep the existing i18n
  wording (`Artifacts`/`Verification`); the session plan review keeps its
  approval fields instead of the prototype's add-step/inline-edit (those live
  in the New Task flow, which received the same card palette).

## Gaps / deferred

- Tab label wording harmonization (`Artifacts`→`Artifact`,
  `Verification`→`Verify`) — deliberately not churned (both locales pinned by
  existing keys); a copy pass is a product decision.
- Light-theme plan-card tokens are defined (parity-enforced) but only the dark
  theme was screenshot-verified, same as phases 5b/6.
- Focus-ring muting (`#2e8ba5` + soft glow) still pending from phase 1 notes.
- Full `DesktopRightSidebar` QA harness remains deferred from phase 5a.

---

# FINAL VERIFICATION — 2026-09-11 21:36 CST

Independent final verification of the 7-phase refactor. No code changes were
made; no commits. All gates were run as individual steps mirroring
`agi-stack/Makefile` lines 102-114 (`desktop-check` + `desktop-deps`) and
110-111 (`desktop-browser-qa`). Logs and screenshots:
`artifacts/desktop-refactor/final/`.

## Gate results

| # | Gate (Makefile step) | Result | Numbers | Log |
|---|---|---|---|---|
| 0 | `desktop-deps` — `CI=true pnpm install --frozen-lockfile` | PASS | Already up to date, 170 ms | `final/00-pnpm-install.log` |
| 1a | `pnpm run build:workspace-core:debug` | PASS | `dev` profile finished in 3.88 s | `final/01-workspace-core-debug.log` |
| 1b | `cargo build -p agistack-desktop-sidecar` | PASS | `dev` profile finished in 0.98 s | `final/02-cargo-build-sidecar.log` |
| 1c | `cargo test -p agistack-desktop-sidecar` | PASS | **862 passed / 0 failed / 1 ignored** (24.06 s) | `final/03-cargo-test-sidecar.log` |
| 1d | `pnpm test` with `AGISTACK_REAL_SIDECAR` + `AGISTACK_REAL_WORKSPACE_CORE` | PASS | **4589 tests / 4588 pass / 0 fail / 0 cancelled / 1 skipped** (16.19 s) | `final/04-pnpm-test.log` |
| 1e | `pnpm run build:electron` (electron-vite main/preload/renderer) | PASS | built in 10.12 s; largest chunk `index-WxLk4VjP.js` 10,095.50 kB | `final/05-build-electron.log` |
| 2 | `desktop-browser-qa` — `CI=true pnpm run qa:browser` | PASS | **8 passed / 0 failed** (5.1 s) | `final/06-browser-qa.log` |

Note on gate 1d: the actual full-suite tally is 4589 tests / 4588 pass /
1 skipped, which differs slightly from the phase-7 baseline recorded above
(4586 pass / 3 skipped). The delta is +2 pass / -2 skipped — the suite is
fully green either way; exit code 0. No test was removed or weakened by this
verification (read-only run).

## Visual sweep (1440x1024, dark, vite @ 127.0.0.1:5199)

Script: `final/final-screenshot.mjs` (Playwright chromium, `colorScheme:
'dark'`, 900 ms settle after `networkidle`). Assertions per page: zero
`console.error` / `pageerror`, and `scrollWidth === clientWidth` (no
horizontal overflow). Result: **CONSOLE CLEAN** and **OVERFLOW CLEAN** on all
10 fixtures (`final/07-visual-sweep.log`). Vite was started and killed in the
same shell chain; port 5199 verified free afterwards (a lingering process was
found on first check and killed; only the process spawned by this
verification was touched).

| Fixture | Screenshot | Console | Overflow | Visual assessment |
|---|---|---|---|---|
| mission-control | `final-mission-control-1440.png` | clean | none | OK — dark shell, sidebar with workspace tree + status dots, centered new-thread composer with picker chips, recent threads list |
| session-conversation | `final-session-conversation-1440.png` | clean | none | OK — user bubble, thinking block, tool-activity strip with metric chips, syntax-highlighted code block, sub-agent card |
| login-sso | `final-login-sso-1440.png` | clean | none | OK — device-code modal (`N7QK 4X2P`) over dimmed login surface; modal styled, CTA palette correct |
| new-task-flow | `final-new-task-flow-1440.png` | clean | none | OK — 3-step wizard header, task form left, planning-context rail right with toggles and plan-first protection note |
| provider-settings | `final-provider-settings-1440.png` | clean | none | OK — settings nav + provider list; main panel shows the styled, expected `desktop_sidecar_launch_capability_required` empty/error state with retry (browser fixture has no sidecar; consistent with phase-6 captures) |
| session-plan-review | `final-session-plan-review-1440.png` | clean | none | OK — versioned_atomic · v7 chip, numbered step rows, approval card with environment/permission selects and cyan approve CTA |
| session-evidence | `final-session-evidence-1440.png` | clean | none | OK — tab bar with count badges (Artifacts 2 · Sources 2 · Checks 3), authoritative sources list with verified/Missing badges |
| search | `final-search-1440.png` | clean | none | OK — retrieval-mode chips, query input + CTA, empty-state panel; QA state-switcher pills at top are fixture controls |
| automations | `final-automations-1440.png` | clean | none | OK — list + detail layout, schedule/timezone/run-history cards, revision-guarded notice banner |
| workspace-collaboration | `final-workspace-collaboration-1440.png` | clean | none | OK — 10-tab canvas, Goals/Tasks list view with objectives and tasks columns |

No unstyled areas, palette regressions, or element overlap observed in any
fixture.

## Verdict

**ALL GATES PASS.** The refactor is verified end-to-end: Rust sidecar build +
862 unit tests, full desktop suite 4588/4589 green with the real sidecar and
workspace-core binaries, Electron bundle build, 8/8 browser integration
tests, and a 10-fixture visual sweep with zero console errors and zero
horizontal overflow.
