# Desktop conversation rendering — web parity redesign 2026-09

Restyles the MemStack desktop client's conversation rendering to visually match the
MemStack web frontend (`web/src` agent chat). Pure CSS/token value changes plus one
design-contract test update. No TSX/DOM restructure, no class renames, no commits.

## Files changed

| File | What changed |
|---|---|
| `agi-stack/apps/desktop/src/styles/tokens.css` | Core scale values mirrored to the web `@theme` scale (both `:root` dark and `:root[data-theme='light']`); 11 new chat/bubble tokens added to both blocks |
| `agi-stack/apps/desktop/src/features/chat/ChatPanel.css` | Bubble anatomy (user + assistant surfaces, avatar chip, row widths, meta colors), chat background, base chat text 14px/1.5, link style (primary color, underline on hover), thought-card italic secondary text, 5 mono font stacks aligned |
| `agi-stack/apps/desktop/src/features/chat/ChatTimeline.css` | Markdown prose rhythm (4px, code 8px), inline code chip, code-block frame (bg/radius/label/fade), streaming caret (2px content-color block), error surfaces (`timeline-error`, `agent-run.failed`), mono font stacks |
| `agi-stack/apps/desktop/tests/chat-narrative-presentation.test.mjs` | One pinned value updated: user bubble background token `--desktop-surface-29` → `--desktop-bubble-user-bg`, with a "web parity redesign 2026-09" justification comment |

## Token table (important values, old → new)

Dark (`:root`):

| Token | Old | New (web parity) |
|---|---|---|
| `--desktop-panel` | `#171717` | `#121212` |
| `--desktop-panel-2` | `#1a1a1a` | `#181818` |
| `--desktop-panel-raised` | `#1a1a1a` | `#1f1f1f` |
| `--desktop-border` | `#242424` | `#333333` |
| `--desktop-text` | `#f4f4f4` | `#f2f2f2` |
| `--desktop-muted` | `#a1a1a1` | `#a3a3a3` |
| `--desktop-faint` | `#737373` | `#6b6b6b` |
| `--desktop-cyan` / `--desktop-accent` | `#ededed` | `#f2f2f2` |
| `--desktop-cyan-rgb` | `237, 237, 237` | `242, 242, 242` |

Light (`:root[data-theme='light']`):

| Token | Old | New (web parity) |
|---|---|---|
| `--desktop-panel-2` | `#f5f5f5` | `#f7f7f7` |
| `--desktop-border` | `#e5e5e5` | `#e3e3e3` |
| `--desktop-text` | `#222222` | `#262626` |
| `--desktop-muted` | `#666666` | `#4f4f4f` |
| `--desktop-faint` | `#7e7e7e` | `#6b6b6b` |

New tokens (dark / light):

| Token | Dark | Light |
|---|---|---|
| `--desktop-chat-bg` | `#0a0a0a` | `#f8fafc` |
| `--desktop-bubble-user-bg` | `#1f1f1f` | `#f8fafc` |
| `--desktop-bubble-user-border` | `#2e2e2e` | `#e5e5e5` |
| `--desktop-bubble-agent-bg` | `#181818` | `#ffffff` |
| `--desktop-bubble-agent-border` | `#333333` | `#e3e3e3` |
| `--desktop-inline-code-bg` | `#262626` | `#f1f5f9` |
| `--desktop-code-block-bg` | `#141414` | `#f7f7f7` |
| `--desktop-code-block-bg-rgb` | `20, 20, 20` | `247, 247, 247` |
| `--desktop-error-bubble-bg` | `#231115` | `#fef2f2` |
| `--desktop-error-bubble-border` | `#5d3239` | `#fecaca` |
| `--desktop-error-bubble-text` | `#ff9aa4` | `#991b1b` |

## Bubble anatomy (web MessageBubble → desktop CSS)

- User: right-aligned, `max-width: 85%`, `padding: 8px 16px`,
  `border-radius: 8px 8px 2px 8px` (bottom-right sharp), 1px subtle border,
  whisper shadow. Was: 82%, 12px 14px, 12px 12px 3px, `--desktop-surface-29`.
- Assistant: left-aligned, `max-width: 94%` row, new bordered card
  (`padding: 10px 16px`, `border-radius: 2px 8px 8px 8px` top-left sharp,
  `#181818`/`#ffffff` background, whisper shadow). Was: unbordered plain text.
- Avatar: 28px → 32px, primary-tinted background (10%) + ring (15%); user
  avatar gets the neutral slate variant.
- Chat text: 11px/1.62 muted → 14px/1.5 content color.
- Markdown prose: sibling rhythm 8px → 4px (framed code keeps 8px), lists 2px,
  inline code mono 0.93em on `--desktop-inline-code-bg` with 2px 4px padding,
  code frame bg `#141414`/`#f7f7f7`, radius 8px, 10px uppercase language label
  at 0.08em tracking, 13px JetBrains Mono body.
- Streaming caret: 7px cyan block → 2px block in `currentColor` (blink kept,
  reduced-motion guard kept).
- Links: always-underlined cyan → primary color, underline on hover only.
- Thought card content: 11px upright → 12px italic secondary.
- Mono stack everywhere: `'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.

## Test results

Full `pnpm test` in `agi-stack/apps/desktop` (final run):

- tests 4589, pass 4586, fail 0, cancelled 0, skipped 3, duration ~9.5s

Contract tests touched by the redesign:

- `design-tokens.test.mjs` — unchanged; passes (hex budget 0 kept: all new
  colors introduced as token definitions only; every new `var(--desktop-*)`
  reference resolves; light/dark token parity intact).
- `theme.test.mjs` — unchanged; passes (light block overrides exactly the dark
  token set including the 11 new tokens; `--desktop-code-block-bg-rgb` matches
  its named light hex; meta theme-color values untouched: `#0a0a0a`/`#ffffff`).
- `desktop-shell-fidelity.test.mjs` — unchanged; passes (no structural pins
  were affected).
- `chat-narrative-presentation.test.mjs` — one assertion updated (user bubble
  background token), with justification comment. Passes.
- `render-performance-budget.test.mjs` — unchanged; passes (no new keyframes;
  caret animation keeps its reduced-motion guard).

## Screenshots (artifacts/desktop-redesign/)

- `before` reference: `/tmp/current-session-conversation.png` (pre-redesign capture)
- `after-dark.png` / `after-light.png` — session conversation, top of thread
- `after-dark-tall.png` — full thread incl. second user bubble + sub-agent cards
- `after-dark-bottom.png` / `after-light-bottom.png` — bottom-of-thread attempt
- `forced-skill-dark.png` / `forced-skill-light.png` — forced-skill badge fixture
- `canonical-story-dark.png` / `canonical-story-light.png` — canonical story fixture

Visual assessment vs the web spec: asymmetric radii confirmed (user
bottom-right sharp, assistant top-left sharp), assistant bubble is a bordered
card on the panel ladder with a tinted 32px avatar, user bubble is
right-aligned at 85% max-width, code frames/inline chips/thought card match
the web treatments, and both themes stay correct.

## Deliberately NOT changed

- Composer (`--session-composer-radius: 8px`, control radius 6px, 11px font):
  pinned by `chat-narrative-presentation.test.mjs` and out of the bubble scope.
- Tool groups, HITL cards, work-plan/artifact cards, aggregated sources:
  adjacent surfaces; only their inherited token values shifted. Verified via
  fixtures — no regressions.
- Legacy `.message.transcript-message.{agent,user,runtime}` left-accent rules
  in `ChatTimeline.css`: only apply outside `.session-chat-narrative`
  (overridden inside it); left to avoid touching non-narrative renderers.
- `.radix-themes.light` scoped overrides: new styles are token-driven, so the
  light theme works through `tokens.css` alone; existing overrides untouched.
- Markdown code fence behavior (collapse/wrap toggles), highlight.js palette:
  spec asked to keep CodeBlockFrame/highlight.js as-is.
- The 11 new tokens deliberately avoid the `migratedHexLiterals` /
  `migratedChannels` ban lists by living in token definitions (the only place
  raw literals are allowed by `design-tokens.test.mjs`).

## Process notes

- QA fixture vite server (`127.0.0.1:5199`) was started per screenshot batch
  and killed after each; port verified free at the end
  (`lsof -iTCP:5199 -sTCP:LISTEN` → empty). An older orphaned vite from a
  previous session (PPID 1) was also found and killed.
- Light-theme captures were produced by injecting
  `document.documentElement.dataset.theme='light'` plus swapping the Radix
  `dark`→`light` class (the fixture hard-codes `appearance="dark"`).

---

# Phase 2 — conversation-flow surfaces (tool/subagent/skill/HITL cards)

Restyles the remaining conversation-flow surfaces to the web reference
(`web/src/components/agent/timeline/ExecutionTimeline.tsx`,
`timeline-items/{AgentToolCards,ToolItems,shared}.tsx`,
`timeline/SubAgentTimeline.tsx`, `chat/MessageStream.tsx`
`ToolExecutionCardDisplay`). Same constraints as phase 1: CSS/token value
changes only, no class renames, no DOM/TSX restructure, dark+light parity.

## Files changed

| File | What changed |
|---|---|
| `agi-stack/apps/desktop/src/styles/tokens.css` | 3 new tokens added to BOTH `:root` dark and `:root[data-theme='light']` blocks |
| `agi-stack/apps/desktop/src/features/chat/ChatTimeline.css` | Status-pill vocabulary (10px font-medium rounded-full: running=amber, done=green `#35d399`, error=red `#ff6978`), 10px uppercase tracking-wide section micro-labels, expanded detail body mono 13px/1.6, 28x28 tool-call icon chip with 1px ring + status tints, 13px medium row titles, HITL response/approval-evidence cards to 8px radius |
| `agi-stack/apps/desktop/src/features/chat/ChatPanel.css` | Tool-call rows inside the tool group render as bordered execution cards (8px radius, bubble surface, whisper shadow); tool-group summary header 12px medium / 10px meta; aggregated-sources card aligned to the card frame; subagent group indigo identity (name chip, icon chip, running border, 4px indigo progress bar, indigo active phase chip); skill card aligned to the same frame with 13px semibold title, 10px micro-labels, 4px indigo progress bar |

No `.tsx` files were edited; no test files were edited (see below).

## Token additions (both blocks)

| Token | Dark | Light |
|---|---|---|
| `--desktop-shadow-card` | `0 1px 2px rgba(15, 23, 42, 0.02)` | same (web step-card whisper shadow verbatim) |
| `--desktop-indigo-chip-bg` | `rgba(99, 102, 241, 0.25)` | `#e0e7ff` (web indigo-100) |
| `--desktop-indigo-chip-text` | `#818cf8` (web indigo-400) | `#4f46e5` (web indigo-600) |

Existing tokens reused: `--desktop-green`/`--desktop-red`/`--desktop-amber`
(+ their `-rgb` channels) for the status pills, `--desktop-indigo-rgb` for
indigo tint borders/tracks, `--desktop-indigo-bright` for progress fills,
`--desktop-bubble-agent-bg`/`-border` for all card frames.

## Surface mapping (web → desktop)

- Tool call groups: the `<details class="timeline-tool-group">` container
  stays borderless/transparent (web ExecutionTimeline group is unbordered;
  each step is the card). Each `ToolCallPairView` row inside
  `.timeline-tool-group-items` is now the collapsible execution card:
  1px `--desktop-bubble-agent-border`, 8px radius, `--desktop-bubble-agent-bg`,
  `--desktop-shadow-card`, 28x28 icon chip with 1px ring (running=amber /
  complete=green / failed=red tint), 13px medium tool name, status pills in
  the shared vocabulary, expanded details indented 34px (28px chip + 6px gap)
  with 10px uppercase micro-labels and mono 13px/1.6 input/output.
- AggregatedSourcesCard: same card frame (8px/bubble border+surface/whisper
  shadow), 12px semibold title, 10px metrics.
- SubAgentGroupView: card on the bubble surface (gradient + raised shadow
  removed), indigo name chip (`--desktop-indigo-chip-*`), indigo default icon
  chip (success/error keep green/red), indigo running border, 4px
  rounded-full indigo progress bar (was 2px gray gradient), indigo active
  lifecycle phase chip, 10px uppercase detail labels, 12px detail body text.
- SkillTimelineCard: same card frame (purple gradient removed), indigo icon
  chip (6px radius), 13px semibold title, 10px meta/labels, 4px indigo
  progress bar (red when failed).
- ThoughtTimelineCard / WorkPlanTimelineCard: verified already on the phase-1
  card vocabulary (bordered 8px surface, uppercase micro-label, secondary
  italic thought text) — no changes.
- HITL (`timeline-hitl-response`, `timeline-approval-evidence`): 7px→8px
  radius, 8px 10px padding, tinted surfaces kept.

## Test results

- Focused `node --test` against `/tmp/agistack-desktop-test-dist`:
  design-tokens, theme, chat-narrative-presentation, skill-timeline-group-model,
  subagent-timeline-group-model, work-plan-timeline-model,
  render-performance-budget, hitl-response-events, forced-skill-message-badge —
  90/90 pass.
- Full `pnpm test` in `agi-stack/apps/desktop` (final run):
  tests 4589, pass 4586, fail 0, cancelled 0, skipped 3 — matches the phase-1
  baseline.
- No contract test pins needed updating: the one structural pin on the tool
  group (`chat-narrative-presentation.test.mjs` — `.timeline-tool-group`
  stays `border: 0; background: transparent`) still holds because the card
  treatment was applied to the inner tool-call rows, not the group container
  (matching the web structure). `design-tokens.test.mjs` hex budget stays 0
  (all new colors live in token definitions; the `15, 23, 42` shadow channel
  is only inside the `--desktop-shadow-card` definition). `theme.test.mjs`
  light/dark token parity holds with the 3 new tokens in both blocks.

## Screenshots (artifacts/desktop-redesign/)

- `phase2-tall-dark.png` / `phase2-tall-light.png` — full session-conversation
  fixture: subagent groups with indigo name chips, skill cards, tool groups
- `phase2-tools-dark.png` / `phase2-tools-light.png` — conversation top
- `phase2-sources-dark.png` / `phase2-sources-light.png` — aggregated sources
  card + tool-call cards inside the tool group
- `phase2-tool-expanded-dark.png` — expanded tool card: OUTPUT micro-label,
  mono 13px/1.6 JSON body, green complete icon chip
- `phase2-thought-dark.png`, `phase2-workplan-dark.png` — confirmed already on
  the phase-1 vocabulary, unchanged
- `phase2-forced-skill-dark.png` — forced-skill badge fixture, no regression
- Shoot scripts: `shoot-phase2.mjs`, `shoot-phase2-tall.mjs`,
  `shoot-phase2-expand.mjs`

Visual assessment: dark and light both match the web look — execution cards
read as bordered rounded cards on the bubble surface, status pills share the
amber/green/red tint vocabulary, subagent groups carry the indigo identity
(chip `#e0e7ff`/`#4f46e5` light, `rgba(99,102,241,.25)`/`#818cf8` dark), and
section labels are 10px uppercase tracking-wide throughout.

## Deliberately NOT changed

- No subagent or HITL QA fixture exists (`qa/` has no `subagent-*.html` /
  `hitl-*.html`, no `SubAgent*Qa.tsx`/`Hitl*Qa.tsx` harness); per the task
  rules no new fixtures were created. The session-conversation fixture covers
  subagent groups (single/parallel/chain, running/complete/error) and skill
  cards; HITL cards were verified through `hitl-response-events.test.mjs`
  plus their shared token vocabulary. The running-state 4px progress bars are
  exercised by `subagent-timeline-group-model.test.mjs` /
  `skill-timeline-group-model.test.mjs` (fixture groups settle to terminal
  states, so no bar renders).
- `.timeline-debug-group` (run activity group) rows stay borderless — web has
  no card treatment for the debug stream.
- MCP app timeline card, memory recall card, artifact cards: adjacent
  surfaces outside the phase-2 scope; they inherit the new tokens only.
- The tool-group container keeps its borderless look and its existing
  contract pin (see above).
- Chevron rotation animations, spinner keyframes, and all
  `prefers-reduced-motion` guards untouched (render-performance-budget
  passes unchanged).
- Thought/work-plan card internals (step numbers, streaming dots) — already
  on the phase-1 vocabulary.

## Process notes

- QA vite server on `127.0.0.1:5199` was started for the screenshot batch and
  killed afterwards; port verified free (`lsof -iTCP:5199 -sTCP:LISTEN`
  → empty).
- Light-theme captures used the same dataset/class swap as phase 1
  (`document.documentElement.dataset.theme='light'` + Radix `dark`→`light`
  class swap) via `shoot-phase2.mjs` / `shoot-phase2-tall.mjs`.
- No commits were made; only `agi-stack/apps/desktop` and
  `artifacts/desktop-redesign/` were touched.
