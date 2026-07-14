# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-07-13
- Primary product surfaces: desktop Login, Home, My Work, New Task, Workspace overview,
  Workspace → Conversation tree, Session workspace, Artifact review, recovery, Search,
  Automations, and the independent Settings resource workbench.
- Canonical visual reference:
  `design-prototype/memstack-desktop-agent-mission-control`.
- Canonical product contract:
  `docs/product/desktop-agent-ui/02-product-prd.md`.
- Canonical interaction and visual specification:
  `docs/product/desktop-agent-ui/03-ui-ux-spec.md`.
- Supporting evidence reviewed:
  - `design-prototype/memstack-desktop-agent-mission-control/src/App.jsx`
  - `design-prototype/memstack-desktop-agent-mission-control/src/styles.css`
  - `design-prototype/memstack-desktop-agent-mission-control/src/components/`
  - `design-prototype/memstack-desktop-agent-mission-control/qa/`
  - `design-prototype/memstack-desktop-agent-mission-control/design-qa.md`
  - `docs/product/desktop-agent-ui/05-workspace-conversation-ux-mapping.md`
  - `docs/product/desktop-agent-ui/06-session-detail-competitive-research.md`
  - `agi-stack/apps/desktop/src/`
  - `agi-stack/apps/desktop/src-tauri/src/local_runtime/`
- Precedence: explicit PRD state, authority, security, and lifecycle requirements override
  prototype mock behavior. The prototype is authoritative for layout, hierarchy, visual language,
  and user-visible flow when it does not conflict with the PRD.

## Brand

- Personality: calm mission control, precise, technically credible, restrained, and enterprise-ready.
- Trust signals: explicit scope, authority, revision, environment, evidence, provenance, and next
  action; secrets and external side effects are never implied or hidden.
- Avoid: chat-first consumer styling, gradients, decorative dashboards, emoji, fake activity,
  fabricated metrics, opaque success states, excessive pills, and panels without a user decision.

## Product goals

- Goals:
  - Make Work and Code two capability modes of one Task/Conversation/Run model.
  - Let a user identify status, execution location, required input, and latest evidence within
    three seconds.
  - Keep plans, permissions, changes, sources, checks, and artifacts reviewable next to the action
    they authorize.
  - Restore authoritative work after restart or disconnection without repeating side effects.
  - Govern Models, Skills, Plugins, and Agents from one searchable, versioned Settings workbench.
- Non-goals:
  - A full IDE, full Git GUI, or general-purpose browser replacement.
  - Exposing model hidden reasoning.
  - Independent Work and Code histories or navigation systems.
  - Treating more panels or metrics as product success.
- Success signals:
  - A completed Task has an authoritative Run state, reviewable evidence, at least one inspectable
    artifact or change, and an auditable human decision trail.
  - Users can finish primary flows by keyboard at the supported compact viewport.
  - Reconnect, approval, and delivery never rely on optimistic local inference.

## Personas and jobs

- Primary personas:
  - Knowledge worker or product owner producing sourced deliverables.
  - Software engineer working with repositories, environments, diffs, tests, and PRs.
  - Reviewer supervising several concurrent Agent tasks.
  - Enterprise administrator governing models, capabilities, permissions, and budgets.
- User jobs:
  - Create a Work or Code Task from a goal and approved context.
  - Preview and revise an Agent-authored plan before execution.
  - Supervise long-running work and handle the single current decision.
  - Inspect sources, tool activity, changes, checks, and immutable artifact versions.
  - Reattach or fork recovery while preserving execution identity and audit history.
  - Configure and understand Provider, Skill, Plugin, and Agent relationships.
- Key contexts of use: long-running desktop sessions, compact laptop windows, several parallel
  tasks, intermittent network/runtime connectivity, and enterprise tenant/project isolation.

## Information architecture

- Primary navigation: New Task, Home, My Work, Automations, Search, the current Project's
  Workspace → Conversation tree, Notifications, Settings, and Account.
- Core routes/screens:
  - Login and trusted-session recovery.
  - Home summary and resume actions.
  - My Work semantic attention queue.
  - New Task: Describe → Agent planning → Human plan review.
  - Workspace overview.
  - Session Header + Narrative Thread + mode-aware Work Canvas.
  - Artifact version review and delivery.
  - Reconnect / Reattach / Fork recovery.
  - Independent Settings window with Account, Workspace, preferences, and AI resources.
- Content hierarchy:
  - Tenant → Project → Workspace → Conversation → Task/Run/Artifact relationships remain explicit.
  - The Global rail shows Workspaces and Conversations only for the current Project.
  - Thread owns intent, explanation, key events, grouped activity, HITL, and Steering.
  - Canvas owns Plan, Changes/Artifact, Terminal/Sources, Checks/Verification, and evidence.
  - Settings owns tenant/project switching and all resource governance.

## Design principles

- Status before process: authoritative state, environment, and required action precede logs.
- Work surface before chat: the Conversation explains; the Canvas proves and delivers.
- One current decision: highlight one human gate and queue the rest.
- Environment never disappears: Code shows Local/Worktree/Cloud, branch, and working directory;
  Work shows project, privacy, and external-data scope.
- Explicit state over semantic inference: UI states derive from structured fields, not text matching.
- Progressive technical depth: default to outcome and evidence; reveal raw calls and identifiers on
  demand.
- Provider-first model governance: a Credential belongs to one Provider; model selection and
  workspace routing remain separate operations.
- Tradeoffs: dense desktop information is acceptable when hierarchy is clear; do not trade away
  identity, authority, or evidence merely to reduce visual density.

## Visual language

- Color:
  - Background `#080C12`; primary panel `#0F141D`; secondary panel `#151A24`.
  - Border `#242B36`; soft border `#1B222E`.
  - Text `#E7EDF6`; muted `#9AA5B5`; faint `#687386`.
  - Cyan `#38D6FF` for active selection and primary affordance.
  - Green `#35D399` for explicit success, amber `#F0B35A` for attention/approval, red
    `#FF6978` for explicit failure or destructive risk.
  - Work mode violet is an identity accent only; no gradients.
- Typography: Inter/SF Pro/Segoe/system sans for UI; SFMono/Menlo/Consolas for code and terminal.
  Body 14/20, secondary 12/16, page title 18/24 weight 600, compact metadata 8–11 where the
  reference requires it but never for primary authored content.
- Spacing/layout rhythm: 4/8/12/16/24/32 spacing; 28 compact, 32 default, 36 primary control
  heights; 220px desktop Global rail and 200px compact Global rail.
- Shape/radius/elevation: 6–8px panel radius, 1px structural borders, pills only for status/mode/
  filters, shadow only for menus and modal windows.
- Motion: short state transitions only; no animation that substitutes for authority. Honor reduced
  motion.
- Imagery/iconography: existing MemStack mark and real avatar assets; one outline icon family,
  normally 14/16/20px; no emoji or approximate handcrafted icons.

## Components

- Existing components to reuse:
  - `LoginScreen`, `NewTaskFlow`, `MyWorkQueue`, `SessionWorkspace`, `SessionEvidenceCanvas`,
    `SettingsWindow`, and `ProviderDetailEditor`.
  - Current Radix primitives, tokens in `agi-stack/apps/desktop/src/styles.css`, API adapter, and
    authoritative Rust local-runtime stores.
- New/changed components:
  - Home and global Search/Command Palette surfaces grounded in live data.
  - Automations master/detail uses an explicit `Manual | Schedule | Event` Trigger union. Schedule
    owns `At | Every | Cron`; Environment and Permission profile belong to the definition, not to
    inferred run state. Create, edit, enable/pause, and Run now remain fail-closed unless the server
    returns the corresponding action capability, revision, and idempotent mutation contract.
  - Every automation mutation enters one `AutomationCommandService`. A Run now intent carries the
    authenticated Tenant/Project/actor scope, `expected_revision`, and `Idempotency-Key`; one
    caller-owned database transaction reserves a replayable receipt and writes the queued Run plus
    fenced `execute_run` operation. The Run ID is also the Agent `message_id`/runtime execution ID,
    so dispatch retries and terminal projection never correlate by job name, prompt text, or time.
    Receipt acceptance means queued, not successful. Capabilities remain false until a production
    worker, real Agent terminal lifecycle persistence, and idempotent terminal projection are all
    enabled and fault-injection verified.
  - Provider Overview/Connection/Models/Routing/Usage tabs and Add Provider wizard.
  - Type-specific Skill, Plugin, and Agent workbenches with draft/version/audit states.
  - Real Browser/Preview canvas and structured evidence Steering references.
  - Recovery diagnosis and environment-specific Reattach/Fork UI.
- Variants and states: loading, empty, read-only, dirty edit, saving, validation-only, externally
  probed, connected, attention, revision conflict, disabled, offline, and permission denied.
- Token/component ownership: extend `agi-stack/apps/desktop/src/styles.css` and existing feature CSS;
  do not create a parallel design-system layer.

## Accessibility

- Target standard: WCAG 2.2 AA.
- Keyboard/focus behavior: every primary flow, tree branch, Canvas tab, decision, plan edit, resource
  mutation, and modal action is reachable with a visible focus ring. Preserve Cmd/Ctrl shortcuts
  documented by the UI spec.
- Contrast/readability: status always includes text or accessible labels; Diff includes +/- and text,
  not only red/green.
- Screen-reader semantics: use landmark regions, real headings, tabs, dialogs, tree semantics where
  appropriate, and restrained `aria-live` only for phase/attention changes.
- Reduced motion and sensory considerations: honor `prefers-reduced-motion`; never rely on motion or
  color alone.

## Responsive behavior

- Supported breakpoints/devices: primary baseline 1440×1024; production must remain usable at
  1280×800. The approved prototype and visual regression suite additionally exercise 1100×800.
- Layout adaptations:
  - ≥1440: Global rail + Thread/Queue + Canvas; optional decision rail only when needed.
  - 1280–1439: retain Mode, Environment, state, and primary action; demote usage/elapsed.
  - 1100 reference: 200px Global rail, about 355px Thread, adaptive Canvas; no page-level horizontal
    overflow.
  - Settings: centered popup, max about 1180×820; compact rail + 244px catalog at 1100.
- Touch/hover differences: desktop keyboard/mouse is primary; hover supplements but never hides the
  only label or action.

## Interaction states

- Loading: render Shell and authoritative Header first; name the delayed surface, such as “Loading
  diff” or “Reconnecting terminal”.
- Empty: explain the current job and offer one primary action; never fabricate activity counts.
- Error: show location, last successful checkpoint, side-effect status, and a specific recovery
  action; diagnostics are copyable and collapsed by default.
- Success: show the server-returned revision/receipt/result; do not infer success from a completed
  animation.
- Automations: read responses redact credential material and declare action capabilities. A missing
  durable scheduler/outbox, execution principal, or reconciliation state is a visible unavailable
  capability, never a client timer or a pre-written successful Run.
- Disabled: explain missing permission, unavailable environment, incomplete configuration, or stale
  revision next to the control.
- Offline/slow network: distinguish Reconnecting, Disconnected, Failed, Reattach, and Fork recovery.
  Retry is not a substitute for recovery semantics.

## Content voice

- Tone: concise, factual, calm, and action-oriented.
- Terminology: Task is the user goal; Conversation is the collaboration stream; Run is one
  authoritative execution; Workspace is a Project-scoped collaboration container; Artifact Version
  is immutable.
- Microcopy rules:
  - Use concrete verbs and objects: “Approve 6 file changes”, “Deliver approved version”,
    “Validate configuration”.
  - Avoid “Continue”, “Proceed”, “Working”, and unqualified “Thinking”.
  - State who or what is waiting: “Needs your input”, “Paused by you”.
  - Preserve technical identifiers, paths, model names, authored content, and code across locales.
  - Local Provider validation with `probed: false` must never say connected or healthy.

## Implementation constraints

- Framework/styling system: React 19 + TypeScript + Vite + Radix UI; Tauri/Rust local runtime;
  Python/FastAPI remains the cloud/reference backend. Use existing feature modules and direct imports.
- Design-token constraints: current `--desktop-*` tokens are the production mapping of prototype
  `--bg/--panel/--border/...` tokens; extend them instead of introducing hard-to-govern themes.
- Performance constraints: cold Shell p95 ≤3s; readable Task switch p95 ≤1s; reconnect state p95
  ≤3s; large lists should be incrementally loaded or virtualized.
- Compatibility constraints: macOS and Windows are primary; Linux is P1. Local and Cloud API
  differences belong in `DesktopApiClient`, not UI conditionals spread across components.
- Security constraints: never persist plaintext session tokens, Provider credentials, or environment
  secrets; every tenant/project/resource/run mutation is scope-checked and revision-guarded.
- Architecture constraints: subjective risk, routing, or quality judgments come from structured Agent
  tool calls. Deterministic UI code only presents structured decisions and protocol facts.
- Test/screenshot expectations:
  - Add pure model/API/Rust tests for every new authority or state transition.
  - Run frontend tests/build and Rust test/fmt/clippy.
  - Capture 1325px and 1100px visual evidence for user-facing changes.
  - Persist a Visual Verdict score of at least 90 under `.omx/state/<scope>/ralph-progress.json`.

## Open questions

- [ ] Choose the production OS credential-vault implementation for trusted sessions and Provider
  secrets on macOS/Windows; owner: desktop platform; impact: restart recovery and NFR-011.
- [ ] Define the supported local Provider discovery/probe contract, including timeouts and network
  permission; owner: runtime; impact: Models Connection and discovery states.
- [ ] Confirm whether 1100×800 remains an official production target or only a visual-regression
  stress target below the PRD's 1280×800 minimum; owner: product/design; impact: density choices.
- [ ] Define Cloud environment provisioning and remote terminal lifecycle; owner: platform; impact:
  Code environment selector and recovery.
- [ ] Define governed configuration version/audit event schemas shared by Skills, Plugins, Agents,
  and routing policies; owner: product/backend; impact: publish/edit histories.
- [ ] Complete packaged macOS and Windows assistive-technology validation; owner: QA; impact: final
  WCAG sign-off.
