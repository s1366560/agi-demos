# Desktop Capability Audit — Pass 5 (rendering parity + visual-element removal + live E2E)

Scope: the 2026-09-20 goal — re-audit/fix the seven desktop capability areas (workspace,
simple chat, skills, plugins, tool calls, agent, subagent) AND finish the conversation-flow
rendering redesign to match the web app, removing unnecessary visual elements.

Baseline at pass start: renderer 4859 pass / sidecar 932 pass / `build:electron` clean.
Final state: **renderer 4863 pass / 0 fail / 3 skip · sidecar 932+3 pass / 0 fail ·
`build:electron` clean · live E2E 7/7 PASS · zero lingering processes.**

## 1. Divergence re-check (vs 2026-09-16 parity audit)

10 of 12 audited divergences were already fixed in-tree (verified with file:line evidence);
§1.10 (avatar-offset) partially, §1.12 (virtualization) open by decision. This pass closed
the residuals and the "unnecessary visual elements" inventory:

| Item | Change | Evidence |
|---|---|---|
| Residual cyan text hues (~20 call sites) | Neutralized to the gray ladder in both themes (forced-skill badge, attachment/artifact icons, turn-collapse hovers, activity eyebrow, pinned/summary/comparison tints, aggregated-source links, memory filters, MCP open action, composer chips) | `ChatPanel.css`, `RunCompletionSummaryCard.css`, `CanonicalStoryCard.css`, `ComposerMenus.css`, `tokens.css` |
| Radix cyan "Live" badge | `color="gray"` (CurrentActivityHeadline kept, neutral) | `ChatPanel.tsx:1671` |
| Identity row | Session variant now renders the web anatomy — 2xs timestamp only; name label + role badge removed (slots kept optional for the workspace variant's sender/mention data) | `ChatTranscript.tsx:167-182`, `ChatTimeline.tsx` |
| Thought card | Icon pulse + blue streaming tint removed; wall-clock → live duration badge (`thoughtTimelineDurationMs`, 1s tick while streaming; +2 model tests); Brain glyph + streaming dots kept (web parity) | `ThoughtTimelineCard.tsx`, `chatTimelineModel.ts`, `ChatPanel.css:1134-1305` |
| Work-plan card | Wall-clock dropped (no duration data exists; never wall-clock) | `WorkPlanTimelineCard.tsx:64` |
| HITL card | Uppercase eyebrow type label + wrapping row chrome removed; card renders standalone (web anatomy) | `ChatTimeline.tsx` (TimelineItemView), `ChatPanel.css:4401-4525` |
| Args-stream caret | Removed (markup + CSS + keyframes); parity test now asserts NO caret | `ChatTimeline.tsx`, `ChatTimeline.css:745-753`, `conversation-flow-parity.test.mjs` |
| Auto-expand on error | `isTimelineItemInitiallyExpanded` returns true for `isError/error` items (standalone failed rows now expand; groups already primed) | `chatTimelinePresentation.tsx:318-327` + behavioral test |
| Runtime rows wall-clock | `timelineRowDurationMs(item)` model — duration or nothing, never wall-clock (+6 model tests) | `chatTimelineModel.ts`, `ChatTimeline.tsx` meta row |
| Avatar-offset coverage | 44px (32px avatar + 12px gap) indent extended to `.mcp-app-timeline-card`, `.timeline-turn-placeholder-shell`; group previews at 70px; §1.10 test pins all | `ChatPanel.css:4360-4372` |
| Workspace variant | Legacy tinted `.message` cards (cyan agent / green user / amber runtime, 28px indent) fully overridden by the session anatomy; runtime rows are borderless neutral text | `ChatPanel.css` workspace-scope selectors |
| Colored worklog icons + hovers | `kind-search`/`kind-edit` tints deleted; 11 `--desktop-text-cyan` hovers → `--desktop-text`; unused `cyan-muted`/`blue-soft` tokens neutralized | `ChatTimeline.css`, `ChatPanel.css`, `tokens.css` |

## 2. Dark-theme blue-steel cast removal (the "reads cyan everywhere" root cause)

The dark `:root` block carried ~215 blue-tinted structural tokens (bg/panel/surface/border/
gray/steel/slate/overlay/glass families + the cyan accent family) while the light theme was
already neutral. All neutralized to luminance-matched pure grays (`neutralize_tokens.py`,
215 tokens + `--desktop-on-accent` → `#101010`); semantic status families
(red/green/amber/teal/purple/indigo/gold/sky/blue) and the running-status cyan
`--desktop-status-running(-rgb)` #38d6ff stay colored, mirroring the light theme's
already-neutralized precedent (kept `border-blue`, `steel-blue`, `purple-checkbox` colored
exactly where light does). 18 light-theme overlay tokens re-synced to the neutral dark
values (theme pair test).

## 3. Radix Theme accent: cyan → gray (monochrome interactive accents)

- `accentColor="cyan"` → `"gray"` in all 5 production Theme roots (`App.tsx` ×2,
  `DesktopAuthenticatedShellSurfaceV2.tsx`, `NewTaskFlow.tsx`, `SettingsWindow.tsx`) and all
  35 QA fixtures — solid buttons/selected tabs/checkboxes now render web-style light-gray.
- 8 explicit decorative `color="cyan"` props → `"gray"` (start-plan button, handoff/agent/
  artifact/language count badges, automations kicker, deliver button); the queue "ready"
  badge → `"green"` (go semantics; emerald is an allowed status family).
- 80 Radix CSS-var usages (`var(--cyan-*)`, `var(--blue-*)`) across 17 CSS files →
  `var(--gray-*)`; 5 genuinely running-state rules remapped to `--desktop-status-running`
  (`.status-executing`, `.status-starting`, my-work running icons, tool-group running em).

## 4. Live end-to-end verification (real profile, real LLM)

Verified against the canonical stack (`make -C agi-stack run-desktop`; sidecar API
`http://127.0.0.1:<ephemeral>`, Bearer session + `X-Agistack-Launch` token):

1. **Workspace** — list (5 pre-existing) + create/get/delete `e2e-smoke-*` round-trip, zero residue. PASS
2. **Simple chat** — new conversation → "hi" → real assistant reply in ~3.4s; instruction-following probe answered `PINEAPPLE-123456` (proves live LLM, no `model_unconfigured`). PASS (temp conversation remains — no delete route exists; clearly labeled)
3. **Skills** — `GET /api/v1/skills/` 200, 4 active definitions. PASS
4. **Plugins** — `GET /api/v1/local-plugins/v2/installations` 200, healthy-empty; marketplace 503 expected in local mode. PASS
5. **Tool calls** — runtime `tool_count: 43` + MCP `echo` tool healthy. PASS
6. **Agent** — 2 definitions (`builtin:all-access`, `desktop_qa_agent`). PASS
7. **Subagent** — 1 active (`desktop_qa_subagent`). PASS

CDP screenshot of the real conversation confirms the redesign in production (monochrome
dark, timestamp-only identity rows, gray accents): `.tmp/desktop-live-e2e-20260920/ui-conversation-e2e.png`.
Fixture-page before/after grids: `.tmp/desktop-visual-qa-20260920/{,after,after2}/`.
Full fixture sweep: session-conversation, message-identity, thought/work-plan cards,
lifecycle, steering, workspace-collaboration, attachments, forced-skill badge — all neutral.

## 5. Verification

- `pnpm test`: 4863 pass / 0 fail / 3 skip (+4 model tests: thought duration, row duration, failed-row expansion).
- `cargo test -p agistack-desktop-sidecar`: 932 + 3 pass / 0 fail (no Rust changes this pass).
- `pnpm run build:electron`: clean (tsc strict, main+preload+renderer).
- Live stack shut down and verified via `ps` — nothing lingers.

## 6. Documented, deliberately not changed

- No list virtualization (§1.12; render-window heuristic retained — architecture, non-visual).
- No Undo button on tool rows (web-only affordance; desktop backend has no undo contract).
- hljs syntax palette drift vs web's react-syntax-highlighter theme (independent palettes).
- Message column stays centered at `max-width: 1440px` (deliberate desktop adaptation).
- Work-plan current step keeps the running-blue tint (running-status semantics, allowed).
- `.agent-run` task-signal cards keep card chrome with now-neutral/status colors.
- `message-identity` QA fixture hardcodes a badge to exercise the optional slot (by design).
