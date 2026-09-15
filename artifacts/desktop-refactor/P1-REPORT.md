# Phase 1 — Visual Foundation: core palette + shell surfaces

Date: 2026-09 (prototype mission-control refactor, phase 1 of N)
Target: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
Scope: `agi-stack/apps/desktop` CSS values + tokens + test pins only. No TSX/DOM/class changes
(the only non-CSS edits are color-literal pins: `index.html` meta theme-color, `public/theme-init.js`,
`src/theme.tsx` meta theme-color constant, and `tests/theme.test.mjs` pins — all required because the
theme-color contract test ties the meta tag to `--desktop-bg`).

## Approach

Git archaeology showed the desktop already shipped this exact blue-tinted mission-control palette
before commit `c1f1cba8f0` ("shift web and desktop palettes to monochrome gray base") desaturated it,
and a later uncommitted "web parity" pass moved core tokens to the web neutral scale. Phase 1 therefore
**restores the pre-monochrome token values** (recovered from `c1f1cba8f0~1:src/styles.css`) and then
**overrides the core scale with the exact prototype values**. The design-tokens contract test's
`migratedHexLiterals`/`migratedChannels` ban-lists confirm these blue-tinted values are the sanctioned
palette (they are prohibited in value position precisely because they belong in tokens.css).

359 dark token values remapped; 10 post-monochrome additions (motion, `--desktop-green-text`, shadow
scale, shadow-card, indigo chip) kept as-is. Dark/light key parity maintained (371 tokens per block).

## Core token remap table (dark)

| Token | Old (web parity) | New (prototype) |
|---|---|---|
| `--desktop-bg` | `#0a0a0a` | `#080c12` |
| `--desktop-panel` | `#121212` | `#0d121a` |
| `--desktop-panel-2` | `#181818` | `#111720` |
| `--desktop-panel-raised` | `#1f1f1f` | `#151c27` |
| `--desktop-border` | `#333333` | `#242d3a` |
| `--desktop-border-strong` | — (new) | `#334154` |
| `--desktop-border-soft` | `#1e1e1e` | `#1b222e` |
| `--desktop-text` | `#f2f2f2` | `#e7edf6` |
| `--desktop-muted` | `#a3a3a3` | `#8996a9` |
| `--desktop-faint` | `#6b6b6b` | `#5d6979` |
| `--desktop-cyan` | `#f2f2f2` (neutral) | `#38d6ff` |
| `--desktop-accent` | `#f2f2f2` (neutral) | `#38d6ff` |
| `--desktop-cyan-rgb` | `242, 242, 242` | `56, 214, 255` |
| `--desktop-surface-cyan` | `#1e1e1e` | `#112b36` (prototype `--cyan-soft`) |
| `--desktop-sidebar-bg` | — (new) | `#0a0f16` |
| `--desktop-chat-bg` | `#0a0a0a` | `#080c12` |
| `--desktop-bubble-user-bg` | `#1f1f1f` | `#161d27` |
| `--desktop-bubble-user-border` | `#2e2e2e` | `#2a3542` |
| `--desktop-bubble-agent-bg` | `#181818` | `#0d121a` |
| `--desktop-bubble-agent-border` | `#333333` | `#242d3a` |
| `--desktop-inline-code-bg` | `#262626` | `#151c27` |
| `--desktop-code-block-bg` | `#141414` | `#090e15` |
| `--desktop-code-block-bg-rgb` | `20, 20, 20` | `9, 14, 21` |

Error-bubble tokens (`#231115` / `#5d3239` / `#ff9aa4`) were already on-palette and are unchanged.
Status colors (`#35d399` / `#f0b35a` / `#ff6978`) unchanged.

The full surface/border/gray/steel/overlay ladders and the cyan accent variant family (~340 more
tokens) were restored to their pre-monochrome blue-tinted values — e.g. `--desktop-surface-7`
`#0f0f0f`→`#0b1017` (titlebar/status-bar/right-rail header = prototype header `#0b1017` exactly),
`--desktop-surface-3` →`#090e15` (deepest inset), `--desktop-cyan-soft` `#a1a1a1`→`#53d0ef`,
`--desktop-on-accent` `#0f0f0f`→`#03141a`.

### Naming decision (deliberate deviation)

The brief asked to "add `--desktop-cyan-soft: #112b36`", but `--desktop-cyan-soft` already exists and
is used in 16 places as a **text/accent color** (ChatPanel, NewTaskFlow, RunCompletionSummaryCard,
settings dialogs). Remapping it to the dark surface `#112b36` would make those texts invisible.
The prototype's `--cyan-soft: #112b36` tinted-surface semantic was therefore mapped onto the existing
tinted-surface token `--desktop-surface-cyan` (now `#112b36`), and `--desktop-cyan-soft` was restored
to its original accent value `#53d0ef` (channels `83, 208, 239`).

### Light theme

Kept the coherent neutral web-parity mapping (bg `#ffffff`, text `#262626`, accent `#262626`).
Only changes: new `--desktop-border-strong: #c9c9c9` and `--desktop-sidebar-bg: #ededed` for parity,
and the 18 `--desktop-overlay-*-rgb` channel tokens synced to the restored dark values — the theme
contract test requires overlays to stay dark translucent and identical across themes (this matched the
pre-monochrome light block exactly).

## Files changed

| File | Change |
|---|---|
| `src/styles/tokens.css` | 359 dark values remapped + 2 new tokens (both blocks) + light overlay sync; comments re-labeled "prototype mission-control refactor 2026-09" |
| `src/styles/chrome.css` | `.copilot-sidebar` background `panel-2` → `var(--desktop-sidebar-bg)` |
| `src/features/navigation/DesktopSidebar.css` | live sidebar root background `surface-18` → `var(--desktop-sidebar-bg)` (one-line value swap; sidebar `#0a0f16` is an explicit phase-1 target) |
| `index.html` | meta theme-color `#0a0a0a` → `#080c12` (color pin, not DOM structure) |
| `public/theme-init.js` | dark theme-color literal → `#080c12` |
| `src/theme.tsx` | dark theme-color literal → `#080c12` (single hex constant; no DOM/class/logic change) |
| `tests/theme.test.mjs` | theme-color pins → `#080c12`, with refactor comment |

`base.css` and `src/app-shell.css` needed no changes — both were already fully token-based.
Pre-existing dirty files from the earlier web-parity task (`ChatPanel.css`, `ChatTimeline.css`,
`chat-narrative-presentation.test.mjs`) were left untouched; they consume the remapped tokens.

## Verification

- `pnpm test` (full suite): baseline 4589 tests / 4586 pass / 0 fail / 3 skipped → after: **4589 /
  4586 pass / 0 fail / 3 skipped**. Identical counts, zero failures. (One intermediate failure —
  light overlay parity — was fixed by syncing the light overlay channels.)
- `design-tokens.test.mjs`: hex budget stays at **0** — no new hard-coded hex outside tokens.css;
  all `var(--desktop-*)` references resolve; no duplicate definitions.
- `theme.test.mjs`: light/dark key parity (371 tokens each), named/rgb channel consistency, overlay
  parity — all green.

## Screenshots (1440x1024)

| Fixture | Before | After |
|---|---|---|
| mission-control | `p1-before-mission-control.png` | `p1-mission-control.png` |
| session-conversation | `p1-before-session-conversation.png` | `p1-session-conversation.png` |
| login-sso | `p1-before-login-sso.png` | `p1-login-sso.png` |
| new-task-flow | `p1-before-new-task-flow.png` | `p1-new-task-flow.png` |

(all under `/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor/`)

### Visual assessment vs oracles

- **mission-control vs `codex-01-home-composer-1440.png`**: palette now matches — app bg reads as
  near-black blue, sidebar is the deeper `#0a0f16` surface, cards/borders are blue-tinted, the cyan
  accent is back (unread badge, "NEW THREAD" eyebrow, active "Work" segment, send button, New thread
  button border/tint). Before-shot was flat neutral black/gray with a white-accent button.
- **session-conversation vs `codex-06-thread-running-1440.png`**: chat surface, user bubble, agent
  panels, code block (deepest inset) and cyan-tinted chips/badges all land in the prototype family.
- **login-sso / new-task-flow**: cyan primary buttons, eyebrows, checkmarks and focus rings restored;
  panels and insets on the blue-tinted ladder.

## Deferred to later phases (clashes / gaps)

- **Selected fill anatomy**: sidebar/task selection currently renders as `rgba(cyan, .10-.16)` tints;
  the prototype uses a solid `#13232d`-`#14222b` fill with a 2 px cyan left bar — structural CSS,
  phase 2 (sidebar).
- **New thread button anatomy**: current cyan border + tint approximates, but the prototype pins
  `#11313e` bg / `#267e96` border / `#dff8ff` text.
- **Focus rings**: now render in bright cyan (restored cyan-ring tokens); the prototype uses the more
  muted `#2e8ba5` border + `0 0 0 3px rgb(56 214 255 / .08)` glow. Tune when touching feature CSS.
- **User bubble bg**: set to `#161d27` per the brief; the prototype conversation screen shows
  `#101720` — a phase-2 (session detail) decision on which screen's anatomy wins.
- **Eyebrow typography** (7-8 px / 800 / .12-.16 em, `#607083`/`#59687a`) — the gray ladder now
  carries these colors, but font-size/weight/spacing rules live in feature CSS, later phases.
- No hard-coded-hex clashes exist in feature CSS (budget 0 held), so no file needed emergency
  tokenization in this phase.

## gitnexus

CSS-value-only change set — symbol impact analysis is N/A (no JS/TS symbols edited; `theme.tsx` and
`theme-init.js` received hex-literal value swaps only). `detect-changes` equivalent for CSS is the
design-tokens/theme contract suite, which is green. No commit made.
