# Desktop vs Web Conversation-Flow Rendering — Parity Audit

Scope: `agi-stack/apps/desktop/src` (Electron renderer) vs `web/src` (React 19 + Tailwind).
Baseline commit audited: `30c368e60` "feat(desktop): align conversation flow rendering with web design language" — it re-pointed desktop tokens to the web monochrome palette, rebuilt bubble/avatar/tool-card CSS, and aligned the composer. This report covers what is **still divergent** after that commit.

## 0. What the last commit already aligned (verified, no action needed)

| Element | Evidence |
|---|---|
| Dark/light palette tokens = web monochrome ladder (#0a0a0a bg, #121212/#181818/#1f1f1f panels, #333/#404040 borders) | `agi-stack/apps/desktop/src/styles/tokens.css:401-499` (dark), `:899-990` (light) vs `web/src/index.css:71-143` + dark shim `:757-816` |
| Typography scale (2xs 10px / xs-plus 11px / xs 12px / code 13px / sm 14px + tracking-label) | `tokens.css:467-476` vs `web/src/index.css:191-265` @theme |
| Radius scale 2/6/8px | `tokens.css:480-482` vs web radius sm/md/lg |
| User bubble: right-aligned, `rounded-lg rounded-br-sm`, hairline border, px-4 py-2, whisper shadow | `ChatPanel.css:1859-1866` vs `web/.../messageBubble/MessageBubble.tsx:955-965` |
| Assistant bubble: 32px avatar + card, `rounded-lg rounded-tl-sm`, px-4 py-2.5 | `ChatPanel.css:1703-1711, 1871-1878` vs `web/.../styles.ts:24-32` (ASSISTANT_BUBBLE/AVATAR) |
| Identity row: label + badge + 2xs timestamp with 11px clock, above bubble | `ChatPanel.css:1761-1848` vs `MessageBubble.tsx:164-187` (MessageTime) |
| Markdown prose rhythm (4px siblings / 8px code frames), inline-code chip, blockquote/table/hr recipes | `ChatTimeline.css:176-329` vs `web/.../styles.ts:14-15` + `web/src/index.css:1763-1784` (.memstack-prose) |
| Tool status pills (10px rounded-full, running=info blue #38d6ff / done=emerald / failed=red) | `ChatTimeline.css:502-534` vs `web/.../chat/MessageStream.tsx:771-798` |
| INPUT/OUTPUT micro labels (2xs uppercase tracking-label) + mono payload blocks | `ChatTimeline.css:555-565, 603-619` vs `MessageStream.tsx:877-904` |
| Artifact card (32px emerald icon block, file strip, meta chips) | `ChatPanel.css:2279-2523`, `ArtifactTimelineCard.tsx` vs `web/.../timeline-items/ArtifactCreatedItem.tsx:290-397` |
| Subagent identity (indigo name chip, status-tinted borders) | `ChatPanel.css:3974-4060` vs `web/.../timeline/SubAgentTimeline.tsx:212-245, 472-478` |
| Composer (6px radius card, 14px input, focus ring) | `ChatPanel.css:4510-4561` vs `web/.../InputBar.tsx:672-682` |
| fade-in-up entrances + reduced-motion fallback | `ChatTimeline.css:1810-1837` vs web `animate-fade-in-up` |
| Fonts (Inter / JetBrains Mono) | `desktop/styles/base.css:20-26` vs `web/src/index.css:191-196` |

Note: all parity overrides live under the `.session-chat-narrative` scope, applied only when `composerVariant === 'session'` (`ChatPanel.tsx:1542-1548`). In the running app this is the conversation-selected state (`App.tsx:7045`), so the live path is covered; but the legacy cyan/amber-tinted `.message` card styles (`ChatTimeline.css:30-55`) still render for the `workspace-chat-panel` variant and QA pages.

---

## 1. Divergences, ordered by visual importance

### 1.1 Tool-call / execution-step anatomy — LARGEST remaining gap

**Web** (`web/src/components/agent/timeline/ExecutionTimeline.tsx:563-714`, used by `MessageArea.tsx:904-916`): a true vertical timeline. Left rail = 24px status circle (border-2 tinted blue/emerald/red, spinning loader while running) with a 1px vertical connector line between steps; duration sits *under* the circle in 2xs tabular-nums. The step card itself is `rounded-md border-slate-200/50 bg-white dark:bg-slate-950/70 px-3 py-2` with preview-first text (`text-xs` tool preview + `text-2xs` step label), auto-expand on error, and an optional Undo button (`:637-649`).

**Desktop** (`ChatTimeline.tsx:823-915` ToolCallPairView, `ChatTimeline.css:334-459`): full-width standalone card rows in a grid `22px | 1fr | auto` — a 28px square status-tinted icon chip, then title (12px medium) + summary inline, then a right meta cluster (diff counts, status pill, duration, wall-clock time). No vertical rail, no connector line, no duration under the icon.

**Gap:** different skeleton (rail+dot+connector vs standalone card rows), different information order (preview-first vs title-first), desktop shows wall-clock time per row where web shows only duration. This is the single most visible difference when a run executes.

### 1.2 Worklog group header / collapsed summary

**Web** (`ExecutionTimeline.tsx:750-829`): header row = chevron + "N actions" title (12px medium) + "N/M done" 2xs + red failed pill + spinner; when collapsed it prints up to 7 one-line action previews + "More N actions" (`:795-813`); old groups default-collapsed (`MessageArea.tsx:912`).

**Desktop** (`ChatPanel.css:2696-2820`, `ChatTimeline.tsx` group rendering): `<details>` summary with 18px icon + title + count + status pill; no collapsed action-preview list, no "N/M done" progress text.

**Gap:** collapsed groups on web still narrate what happened; on desktop they are opaque.

### 1.3 Accent color system (dark theme)

**Web**: dark primary is near-white monochrome (`--color-primary: #f2f2f2`, `web/src/index.css:759-772`); cyan exists only as `--color-info: #38d6ff` for *running* status (`:131-137`).

**Desktop**: cyan `#38d6ff` is the global accent (`tokens.css:20-21, 96`) used across ~205 call sites in chat CSS — assistant avatar tint (`ChatPanel.css:1715-1726`), all focus rings (`:4551-4556`, `timeline-row-toggle`, etc.), forced-skill badge (`:2048-2067`), work-plan count pills and step numbers (`:1385-1393, 1439-1451`), working indicator, selected workflow chips (`ChatTimeline.css:1603-1611`), composer model search focus.

**Gap:** in dark mode the desktop conversation reads cyan-accented where the web reads monochrome-with-blue-status. (Light theme matches: desktop accent #262626 = web primary.) Fixing this is a token-level change (`--desktop-cyan`/`-rgb` in the dark block of `tokens.css`) but has wide blast radius — avatar, focus, selection all flip.

### 1.4 Message action affordance

**Web** (`web/src/components/agent/chat/MessageActionBar.tsx:199-220`): floating pill action bar appears on hover at the bubble's top-right (`-top-3 right-2`, `bg-white dark:bg-slate-800 rounded-lg shadow-sm`), icon buttons inline.

**Desktop** (`ChatTranscript.css` classes in `ChatPanel.css:1889-1968`, markup `ChatTranscript.tsx:184-196`): a 24px kebab `<details>` dropdown inside the meta row, opening a 132px menu.

**Gap:** interaction pattern and placement differ (hover bar on bubble vs kebab menu in header row).

### 1.5 HITL blocks

**Web** (`web/src/components/agent/InlineHITLCard.tsx:1049-1130`, mounted from `MessageBubble.tsx:1921-1990`): standalone card with a rose Shield icon block (w-8 rounded-md), tool name in text-sm medium, risk-level antd Tag, amber/rose risk banner, "Remember this choice" checkbox, Allow/Deny buttons; answered state = emerald/rose outcome panel.

**Desktop** (`HitlResponseCard.tsx:147-196`, `ChatPanel.css:4326-4478`): HITL lives *inside* a worklog `timeline-row` (icon chip + title + expandable details), Radix Theme solid/soft buttons, approval-evidence 2-col grid, and the answered state is a green-tinted `timeline-hitl-response` panel (`ChatTimeline.css:578-601`). Desktop also has the richer `DesktopA2UISurface.tsx` path web lacks.

**Gap:** shell (standalone card vs embedded row), icon identity (rose Shield vs neutral row icon), risk banner, and control styling (antd tags vs Radix buttons) all differ.

### 1.6 Task / todo list — feature gap, not just styling

**Web**: dedicated `web/src/components/agent/TaskList.tsx:21-183` — status icons (Circle/Loader2/CheckCircle2/XCircle/Ban), active-row blue tint, priority dots, and an emerald progress bar header with "N/M completed"; mounted in the right panel. `ExecutionTimeline.tsx:207-258` also summarizes todowrite calls into status-count titles.

**Desktop**: no task checklist panel anywhere in `features/chat`; todo tool calls render as generic tool rows. `features/task/` only contains the new-task creation flow (`NewTaskFlow.tsx`).

**Gap:** web users get a live checklist; desktop users only see opaque tool rows.

### 1.7 Streaming states

**Web** (`web/src/components/agent/message/StreamingAssistantSection.tsx:83-128`): streaming thought → ThinkingBlock; streaming text → a full assistant bubble (avatar + ASSISTANT_BUBBLE_CLASSES) that just grows, **no caret**; plus `StreamingToolPreparation` with a "Preparing" blue pill and live-streaming arguments block (`MessageStream.tsx:843-875`).

**Desktop** (`ChatTranscript.tsx:200`, `ChatTimeline.css:978-995`): appends a 2px blinking block caret inside the bubble; tool calls have only running/complete/failed — no "preparing/streaming-args" state (`ChatTimeline.tsx:917-932` TimelineToolIcon).

**Gap:** caret (desktop-only), and the preparing phase with live argument streaming (web-only).

### 1.8 Code blocks

**Web** (`web/src/components/agent/chat/CodeBlock.tsx:108-200`): `rounded-lg border-slate-200 dark:border-slate-600`, header `bg-slate-200/80 dark:bg-slate-700/80` with normal-case `text-xs font-medium` language label, Copy + **Open in Canvas** buttons; header omitted for short single-line snippets; highlighting via react-syntax-highlighter theme.

**Desktop** (`HighlightedCode.tsx:55-142`, `ChatTimeline.css:810-976`): header is subtler (rgba slate 0.05) with 10px uppercase tracked label, copy only, always shown; adds collapse-after-N-lines with gradient fade (desktop-only, useful); highlighting via hljs with a hand-tuned dark palette (`ChatTimeline.css:922-976`).

**Gap:** header weight/casing, missing Open-in-Canvas equivalent, short-snippet header suppression; syntax color palettes are independently maintained and will drift.

### 1.9 Thought / reasoning card

**Web** (`chat/ThinkingBlock.tsx:100-138`, `messageBubble/MessageBubble.tsx:1135-1181`): Brain/Lightbulb icon in 32px slate chip; title is 2xs uppercase "Thinking" (streaming) or 12px semibold "Reasoning" (persisted); content plain `text-xs` pre-wrap; duration badge right.

**Desktop** (`ThoughtTimelineCard.tsx:31-88`, `ChatPanel.css:1134-1305`): StarIcon (not Brain/Lightbulb); "LIVE" uppercase tag + 3px streaming dots; content is *markdown-rendered* italic 12px (`:1278-1284`); pulsing icon animation while streaming.

**Gap:** icon glyph, LIVE tag, italic markdown content vs plain text. Layout/surface already match.

### 1.10 Message column geometry

**Web** (`MessageArea.tsx:822`): scroll container `p-3 md:p-4 pb-20`, full width; bubbles capped by `MESSAGE_MAX_WIDTH_CLASSES` 92-96% (`styles.ts:38`); timeline rows offset by a `w-8` spacer to align under the avatar (`MessageArea.tsx:905`).

**Desktop** (`ChatPanel.css:865-873`): centered column `max-width: 1120px; padding: 18px clamp(20px, 5.8cqi, 92px) 34px`; user bubble max 84% (`:1617-1622`), assistant body max 92% (`:1709-1711`); timeline rows span full column width with no avatar-offset spacer.

**Gap:** on wide windows desktop is narrower/centered; web timeline items indent under the avatar, desktop's start at the column edge.

### 1.11 Markdown headings

Desktop `.markdown-content` caps h1/h2 at 1.06em/700 and h3+ at 1em/650 (`ChatTimeline.css:211-233`); web `MARKDOWN_PROSE_CLASSES` only sets `font-semibold` + margins, so headings keep the browser's larger scale (`styles.ts:14-15`). Desktop headings read noticeably flatter.

### 1.12 Architecture (non-visual but blocks parity)

Web virtualizes the message list (`MessageArea.tsx:46, 529` — @tanstack/react-virtual); desktop renders the full DOM with a render-window heuristic (`ChatTimeline.tsx:1979` resolveTimelineRenderWindow). Any redesign that adds web-style per-row rails should consider virtualization implications.

---

## 2. Desktop files that would need to change for full alignment

| File | Why |
|---|---|
| `agi-stack/apps/desktop/src/features/chat/ChatTimeline.tsx` | ToolCallPairView/TimelineItemView markup (rail+dot anatomy, preparing state, preview-first text), group collapsed previews (§1.1, §1.2, §1.7) |
| `agi-stack/apps/desktop/src/features/chat/ChatTimeline.css` | timeline-row grid, connector line, status circle, code-block header, streaming caret removal, heading scale (§1.1, §1.8, §1.11) |
| `agi-stack/apps/desktop/src/features/chat/ChatPanel.css` | dark accent usage (cyan→monochrome), group summary header, HITL row overrides, action menu, column width/avatar offset (§1.3, §1.4, §1.5, §1.10) |
| `agi-stack/apps/desktop/src/styles/tokens.css` | dark `--desktop-cyan`/`--desktop-accent` decision (§1.3) |
| `agi-stack/apps/desktop/src/features/chat/ChatTranscript.tsx` | hover action bar vs kebab; caret (§1.4, §1.7) |
| `agi-stack/apps/desktop/src/features/chat/ThoughtTimelineCard.tsx` | Brain glyph, drop LIVE tag, plain-text content (§1.9) |
| `agi-stack/apps/desktop/src/features/chat/HitlResponseCard.tsx` | standalone card shell, rose Shield icon block, risk banner (§1.5) |
| `agi-stack/apps/desktop/src/features/chat/` (new component) | Task checklist panel + todowrite summarization (§1.6) |
| `agi-stack/apps/desktop/src/features/chat/HighlightedCode.tsx` | header casing, short-snippet suppression, optional canvas-open (§1.8) |

## 3. Suggested sequencing

1. §1.3 accent token decision (one-line token change, huge visual effect — decide first because everything else references it).
2. §1.1 + §1.2 tool-call rail + group summaries (the dominant visual during runs).
3. §1.5 HITL card shell (blocking-user-path UI).
4. §1.7 preparing state + caret, §1.9 thought icon, §1.4 action bar (medium).
5. §1.6 task panel (new feature), §1.8/§1.10/§1.11 polish.
