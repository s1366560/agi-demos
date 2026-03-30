# Agent Workspace UI Audit Report

**Project:** MemStack — Enterprise AI Memory Cloud Platform
**Scope:** Agent Workspace (`/tenant/:tenantId/agent`) and supporting layout shell
**Date:** 2026-03-28
**Phase:** 1 of 5 (Audit -> Normalize -> Polish -> Critique -> Harden)
**Status:** Discovery complete. No code changes made.

---

## Executive Summary

The Agent Workspace is the primary user-facing interface of MemStack — an AI agent chat environment supporting multiple layout modes (chat, task, code, canvas). The UI is functional but suffers from significant architectural and design-system debt that impacts maintainability, visual consistency, accessibility, and internationalization.

**Key findings:**

| Severity | Count | Summary |
|----------|-------|---------|
| P0 (Critical) | 1 | Hardcoded Chinese strings break non-Chinese locales |
| P1 (High) | 11 | Monolithic components, dual token systems, pervasive hardcoded colors, duplicate code, missing ARIA labels |
| P2 (Medium) | 12 | Inconsistent spacing, orphaned components, icon system mix, oversized files, duplicate keyboard shortcuts |
| P3 (Low) | 3 | Minor optimizations, unused CSS cleanup, touch target enforcement |
| **Total** | **27** | |

The most impactful remediation targets are:
1. Replace hardcoded colors with semantic design tokens (affects 6+ components)
2. Split the two 1000+ line monoliths (`AgentChatContent`, `ProjectAgentStatusBar`)
3. Fix hardcoded Chinese strings in `ProjectAgentStatusBar`
4. Unify the dual token systems (Tailwind `@theme` vs `antdTheme.ts`)

---

## Scoring Methodology

| Level | Label | Definition | Action |
|-------|-------|------------|--------|
| **P0** | Critical | Blocks users, accessibility violations preventing use, broken functionality for user segments | Fix immediately |
| **P1** | High | Significant UX degradation, maintainability hazards, inconsistency affecting brand perception | Fix in Phase 2 (Normalize) |
| **P2** | Medium | Minor visual inconsistencies, code quality issues, missing polish | Fix in Phase 3 (Polish) or Phase 4 (Critique) |
| **P3** | Low | Nice-to-have improvements, micro-optimizations | Fix in Phase 5 (Harden) or defer |

---

## 1. Architecture and Code Organization

### 1.1 Component Tree

```
TenantLayout (350 lines)
  +-- TenantChatSidebar (848 lines)
  +-- MobileSidebarDrawer
  +-- TenantHeader (600 lines)
  +-- BackgroundSubAgentPanel
  +-- <Outlet> -> AgentWorkspace (182 lines)
        +-- AgentChatContent (1039 lines)
        |     +-- [chat mode] chatColumn + statusBarWithLayout
        |     +-- [task mode] chatColumn + Resizer + RightPanel
        |     +-- [code mode] chatColumn + Resizer + SandboxSection
        |     +-- [canvas mode] chatColumn + Resizer + CanvasPanel
        |
        |   chatColumn contains:
        |     +-- headerExtra (optional)
        |     +-- activeAgentNode banner (optional)
        |     +-- MessageArea (884 lines) / EmptyState (300 lines)
        |     +-- SubAgentMiniMap (if >=3 subagents)
        |     +-- ChatSearch
        |     +-- AgentChatInputArea (96 lines) -> InputBar (664 lines)
        |           +-- InputToolbar, SlashCommandDropdown, MentionPopover,
        |               PromptTemplateLibrary, VoiceCallPanel, FileUploader
        |
        +-- ProjectAgentStatusBar (1137 lines)
        +-- RightPanel (384 lines)
        +-- CanvasPanel
        +-- LayoutModeSelector (131 lines)
        +-- ContextDetailPanel
```

### 1.2 Findings

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| A-01 | **P1** | **Monolithic layout controller.** `AgentChatContent.tsx` at 1039 lines handles layout modes, keyboard shortcuts, state management, export logic, comparison mode, and sandbox management in a single component. | `AgentChatContent.tsx` | Extract into: `useSplitPane` hook, `useWorkspaceKeyboard` hook, `ChatLayoutRouter` component, per-mode layout components. |
| A-02 | **P1** | **Triplicated split-pane logic.** The split-pane layout (left chat + drag handle + right panel) is copy-pasted 3 times for task, code, and canvas modes — identical drag logic, nearly identical JSX structure. | `AgentChatContent.tsx` | Extract a shared `SplitPaneLayout` component that accepts left/right children and mode-specific props. |
| A-03 | **P2** | **Orphaned design components.** `WorkspaceSidebar.tsx` (165 lines), `TopNavigation.tsx` (149 lines), `ChatHistorySidebar.tsx` (233 lines) in `layout/` are prototype/design components not connected to the actual workspace routing or rendering. | `components/agent/layout/` | Delete or archive these files. They add confusion for developers navigating the codebase. |
| A-04 | **P1** | **Duplicate sidebar implementations.** `ConversationSidebar.tsx` (714 lines, agent-level) and `TenantChatSidebar.tsx` (848 lines, layout-level) both render conversation lists with similar but different code. Only `TenantChatSidebar` is actually rendered. | `ConversationSidebar.tsx`, `TenantChatSidebar.tsx` | Consolidate into one implementation. Deprecate and remove `ConversationSidebar` if it is truly unused. |
| A-05 | **P2** | **Two parallel layout systems.** `TenantLayout` wraps the workspace at tenant level while `AgentLayout` exists for project-level agent views — different headers, sidebars, and navigation patterns with no shared abstraction. | `TenantLayout.tsx`, `AgentLayout.tsx` | Document intended usage. If `AgentLayout` is legacy, remove it. If both are needed, extract shared layout primitives. |

---

## 2. Design System and Token Consistency

### 2.1 Current Token Reference

The project defines a comprehensive token system, but it exists in two parallel locations:

**Tailwind CSS v4 tokens** (`web/src/index.css` `@theme` block):

| Category | Tokens |
|----------|--------|
| Primary | `--color-primary: #1e3fae`, `--color-primary-dark: #152d7e`, `--color-primary-light: #3b5fc9`, `--color-primary-glow: #4b6fd9` |
| Background | Light: `--color-bg-base: #f8f9fb`, Dark: `--color-bg-base: #141416` |
| Surface | Light: `--color-surface: #ffffff`, Dark: `--color-surface: #1c1c1f`, `--color-surface-alt: #242428` |
| Border | Light: `--color-border: #e2e8f0`, Dark: `--color-border: #2c2c31` |
| Text | Primary: `--color-text-primary: #1a2332`, Secondary: `--color-text-secondary: #5a6577`, Muted: `--color-text-muted: #7d8599` |
| Status | Success: `#10b981`, Warning: `#f59e0b`, Error: `#ef4444`, Info: `#3b82f6` |
| Typography | Inter (UI), JetBrains Mono (code). Scale: 12/14/16/18/20/24/30/36/48px |
| Spacing | 4px base: 0/4/8/12/16/20/24/32/40/48/64/80/96px |
| Border Radius | 0/4/6/8/12/16/24/9999px |
| Shadows | xs/sm/md/lg/xl/2xl + primary-colored variants |

**Ant Design tokens** (`web/src/theme/antdTheme.ts`):

Mirrors the above values in Ant Design's `token` format (`colorPrimary`, `colorBgBase`, `colorText`, etc.). Values match today but are maintained independently.

### 2.2 Findings

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| D-01 | **P1** | **Dual token systems with divergence risk.** Tailwind `@theme` and `antdTheme.ts` define the same colors independently. No single source of truth. A change in one system won't propagate to the other. | `index.css`, `antdTheme.ts` | Establish one canonical source (recommend `@theme` in CSS) and derive `antdTheme.ts` values from CSS custom properties or a shared constants file. |
| D-02 | **P2** | **Inconsistent spacing usage.** Components use arbitrary spacing combinations (`p-3`, `p-4`, `p-6`, `px-4 py-2.5`, `px-3 py-2`) despite a well-defined 4px-based spacing scale in `@theme`. | Multiple components | Create spacing guidelines mapping use cases to scale values. Audit and normalize all spacing to the defined scale. |
| D-03 | **P1** | **2177 lines of unused CSS utility classes.** `index.css` contains `.btn-*`, `.card-*`, `.badge-*`, `.input-*` utility classes that components do not use — they prefer inline Tailwind classes instead. This is dead CSS increasing bundle size. | `index.css` | Audit usage of each CSS class. Remove unused classes. Keep only genuinely shared utilities that can't be expressed as Tailwind. |
| D-04 | **P2** | **No Tailwind config file.** Using Tailwind CSS v4 inline configuration via `@theme` in `index.css`. While valid for Tailwind v4, this makes the design system harder to reference programmatically (e.g., from `antdTheme.ts`). | `index.css` | Acceptable for Tailwind v4. Mitigate by extracting shared color constants to a `.ts` file imported by both `antdTheme.ts` and referenced in `@theme`. |

---

## 3. Visual Consistency and Hardcoded Values

### 3.1 Hardcoded Color Inventory

The following components bypass the semantic token system and use raw Tailwind color classes:

#### `InputBar.tsx` (664 lines)
```
bg-white dark:bg-slate-800
border-slate-200/60 dark:border-slate-700/60
bg-slate-50/80 dark:bg-slate-900/50
text-emerald-500
text-red-500
text-blue-500
```

#### `ProjectAgentStatusBar.tsx` (1137 lines)
```
text-slate-500
bg-slate-100 dark:bg-slate-800
text-blue-500
bg-blue-100 dark:bg-blue-900/30
text-emerald-500
text-amber-500
text-orange-500
text-red-500
```
(Dozens of instances — the most egregious offender)

#### `LayoutModeSelector.tsx` (131 lines)
```
bg-slate-200/60 dark:bg-slate-700/40
bg-white dark:bg-slate-600
```

#### `Resizer.tsx` (169 lines)
```
hover:bg-slate-200/50 dark:hover:bg-slate-700/50
bg-slate-400/50 dark:bg-slate-500/50
```

#### `AttachmentChip` in `InputBar.tsx`
```
bg-red-50 dark:bg-red-900/20
bg-slate-50 dark:bg-slate-700/50
```

### 3.2 Findings

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| V-01 | **P1** | **Pervasive hardcoded colors bypass semantic tokens.** At least 6 components use raw Tailwind colors (`slate-*`, `emerald-*`, `blue-*`, `red-*`, `amber-*`, `orange-*`) instead of the defined semantic tokens (`bg-surface`, `text-text-primary`, `border-border`, `text-status-success`, etc.). This makes theme changes and dark mode maintenance fragile. | `InputBar.tsx`, `ProjectAgentStatusBar.tsx`, `LayoutModeSelector.tsx`, `Resizer.tsx` + others | Systematically replace all hardcoded colors with semantic token equivalents. Create a mapping guide: `slate-200` -> `border`, `emerald-500` -> `status-success`, etc. |
| V-02 | **P2** | **Mixed icon systems.** Components use both Lucide React (majority) and Material Symbols (`material-symbols-outlined` font). This results in inconsistent icon sizing, alignment, and visual weight. | Multiple components | Standardize on Lucide React. Replace all Material Symbols usage with Lucide equivalents. Remove the Material Symbols font dependency. |
| V-03 | **P2** | **Inconsistent dark mode implementation.** Hardcoded colors use manual `dark:` variant overrides (e.g., `bg-white dark:bg-slate-800`) instead of semantic tokens that automatically adapt. Each new component must manually duplicate all dark mode overrides. | Multiple components | Semantic tokens handle dark mode via CSS custom properties automatically. Replacing hardcoded colors (V-01) will fix this as a side effect. |

---

## 4. Accessibility (a11y)

### 4.1 What Works Well

The codebase has a solid accessibility foundation:

- Skip-to-content link in `TenantLayout`
- `prefers-reduced-motion` respected globally via CSS
- High contrast mode CSS exists
- `role="log"` and `aria-live="polite"` on message container in `MessageArea`
- `Resizer` has full ARIA separator role: `role="separator"`, `aria-valuenow/min/max`, `aria-orientation`, `tabIndex={0}`, keyboard arrow key support
- `LayoutModeSelector` has `aria-pressed` and `aria-label` on each button
- `InputBar` textarea has `aria-label` and `data-testid`
- `dir="auto"` on input for RTL language support

### 4.2 Findings

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| AC-01 | **P1** | **Many interactive elements lack `aria-label`.** Buttons in the header, sidebar, status bar, and toolbar rely on icon-only rendering with no accessible name. Screen readers will announce "button" with no context. | `TenantHeader.tsx`, `TenantChatSidebar.tsx`, `ProjectAgentStatusBar.tsx`, `InputBar.tsx` (toolbar buttons) | Audit all `<button>` and clickable elements. Add `aria-label` or `title` to every icon-only interactive element. |
| AC-02 | **P1** | **Inconsistent focus indicators.** No standardized `focus-visible` ring. Some components show browser-default focus, others show none, and a few have custom focus styles. Keyboard-only users cannot reliably track focus position. | Global / `index.css` | Define a global `focus-visible` style in `index.css` (e.g., `outline: 2px solid var(--color-primary); outline-offset: 2px`). Remove component-level focus overrides. |
| AC-03 | **P2** | **Touch target sizing not consistently enforced.** Some interactive elements meet the 44x44px minimum, but many small buttons (toolbar icons, sidebar actions, status bar controls) appear smaller. | Multiple components | Audit all interactive elements for minimum 44x44px touch target. Use padding to increase hit area without changing visual size where needed. |
| AC-04 | **P2** | **Color contrast unverified for hardcoded combinations.** The semantic token system defines accessible color pairs, but hardcoded colors (e.g., `text-amber-500` on `bg-blue-100`) have not been verified against WCAG 2.1 AA contrast ratios. | `ProjectAgentStatusBar.tsx`, `InputBar.tsx` | After normalizing to semantic tokens, run automated contrast checks. For any remaining custom colors, verify 4.5:1 minimum ratio for normal text, 3:1 for large text. |

---

## 5. Performance

### 5.1 What Works Well

The workspace has strong performance foundations:

- `MessageArea` uses `@tanstack/react-virtual` for message list virtualization
- Streaming tokens are buffered via `deltaBuffers` to reduce re-render frequency
- `streamingAssistantContent` and `streamingThought` are subscribed to narrowly by only the components that display them
- `TenantChatSidebar` uses `requestAnimationFrame`-optimized drag resize
- Per-conversation state is persisted to IndexedDB for fast restore

### 5.2 Findings

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| P-01 | **P2** | **Layout mode changes trigger broad re-renders.** `AgentChatContent` re-renders its entire subtree when layout mode changes (chat/task/code/canvas), including the message list and input bar which are unchanged. | `AgentChatContent.tsx` | Extract each mode's layout into a memoized sub-component. Use `React.memo` or extract the stable chat column so it doesn't unmount/remount on mode switch. |
| P-02 | **P2** | **Status bar polling and subscriptions.** `ProjectAgentStatusBar` (1137 lines) polls pool service on an interval and subscribes to WebSocket lifecycle events. The large component size means any state update re-renders the entire status bar. | `ProjectAgentStatusBar.tsx` | Split into smaller sub-components (`PoolStatus`, `SandboxStatus`, `ExecutionStatus`, `ResourceStatus`, `ContextStatus`) each subscribing to only their relevant state slice. |
| P-03 | **P3** | **2177-line CSS file loaded globally.** Much of `index.css` is unused utility classes. This increases initial CSS parse time and memory usage. | `index.css` | Remove unused CSS classes (see D-03). Consider splitting remaining CSS into critical/non-critical paths. |

---

## 6. Internationalization (i18n)

| ID | Severity | Finding | File(s) | Recommendation |
|----|----------|---------|---------|----------------|
| I-01 | **P0** | **Hardcoded Chinese strings in status bar.** `ProjectAgentStatusBar.tsx` contains hardcoded Chinese: `'未启动'` (Not Started), `'初始化中'` (Initializing), `'就绪'` (Ready), `'执行中'` (Executing), `'已暂停'` (Paused), `'错误'` (Error), `'关闭中'` (Closing). The component imports `useTranslation` but does not use `t()` for these strings. Non-Chinese users see Chinese text in the status bar. | `ProjectAgentStatusBar.tsx` | Replace all hardcoded strings with `t('agent.status.notStarted')`, `t('agent.status.initializing')`, etc. Add corresponding keys to all locale files. |

---

## 7. Code Quality and Maintainability

| ID | Severity | Finding | File(s) | Lines | Recommendation |
|----|----------|---------|---------|-------|----------------|
| Q-01 | **P1** | File exceeds 800-line maximum by 37%. Handles too many responsibilities. | `ProjectAgentStatusBar.tsx` | 1137 | Extract sub-components: `PoolStatusIndicator`, `SandboxStatusIndicator`, `ExecutionStatusIndicator`, `ResourceStatusIndicator`, `ContextStatusIndicator`, `AgentControlButtons`. |
| Q-02 | **P1** | File exceeds 800-line maximum by 30%. Monolithic layout controller. | `AgentChatContent.tsx` | 1039 | Extract: `useSplitPane` hook, `useWorkspaceKeyboard` hook, `SplitPaneLayout` component, per-mode layouts. |
| Q-03 | **P1** | File exceeds 800-line maximum by 6%. Duplicate of `ConversationSidebar`. | `TenantChatSidebar.tsx` | 848 | Consolidate with `ConversationSidebar.tsx` or extract shared logic. |
| Q-04 | **P2** | File exceeds 800-line maximum by 10%. | `MessageArea.tsx` | 884 | Extract scroll management, search integration, and empty state logic into hooks. |
| Q-05 | **P2** | Approaching 800-line limit. Contains functionality that could be shared with `TenantChatSidebar`. | `ConversationSidebar.tsx` | 714 | If `TenantChatSidebar` is the canonical implementation, deprecate this file. |
| Q-06 | **P2** | Duplicate keyboard shortcut registration. Both components register `Cmd+1` through `Cmd+4` for layout mode switching. | `LayoutModeSelector.tsx`, `AgentChatContent.tsx` | — | Remove one registration site. Prefer keeping it in `LayoutModeSelector` since that's the component responsible for mode switching. |
| Q-07 | **P3** | `styles.ts` exports shared style constants (49 lines) but is only partially adopted. | `styles.ts` | 49 | Expand usage or replace with Tailwind `@apply` directives. |

---

## 8. Priority Matrix

This matrix maps all findings to implementation phases:

### Phase 2: Normalize (P0 + P1 issues)

| ID | Finding | Effort |
|----|---------|--------|
| **I-01** | Fix hardcoded Chinese strings in `ProjectAgentStatusBar` | Small |
| **D-01** | Unify dual token systems (Tailwind `@theme` + `antdTheme.ts`) | Medium |
| **V-01** | Replace hardcoded colors with semantic tokens across 6+ components | Large |
| **D-03** | Remove unused CSS utility classes from `index.css` (2177 lines) | Medium |
| **A-01** | Split `AgentChatContent.tsx` (1039 lines) into focused components | Large |
| **A-02** | Deduplicate triplicated split-pane logic | Medium |
| **A-04** | Consolidate duplicate sidebar implementations | Medium |
| **Q-01** | Split `ProjectAgentStatusBar.tsx` (1137 lines) | Large |
| **AC-02** | Standardize focus-visible indicators globally | Small |

### Phase 3: Polish (P2 visual + consistency)

| ID | Finding | Effort |
|----|---------|--------|
| **D-02** | Standardize spacing to 4px scale | Medium |
| **V-02** | Consolidate icon system to Lucide React only | Medium |
| **V-03** | Clean up manual dark mode overrides (resolved by V-01) | — |
| **A-03** | Remove orphaned design components | Small |
| **Q-06** | Remove duplicate keyboard shortcut registration | Small |

### Phase 4: Critique (Accessibility + Performance)

| ID | Finding | Effort |
|----|---------|--------|
| **AC-01** | Add `aria-label` to all icon-only interactive elements | Medium |
| **AC-03** | Enforce 44x44px minimum touch targets | Medium |
| **AC-04** | Verify color contrast ratios | Small |
| **P-01** | Optimize layout mode change re-renders | Medium |
| **P-02** | Split status bar into focused sub-components (if not done in Phase 2) | — |

### Phase 5: Harden (Remaining P2-P3 + robustness)

| ID | Finding | Effort |
|----|---------|--------|
| **Q-04** | Reduce `MessageArea.tsx` to under 800 lines | Medium |
| **Q-05** | Deprecate/remove `ConversationSidebar.tsx` | Small |
| **A-05** | Document or consolidate dual layout systems | Small |
| **D-04** | Extract shared color constants for programmatic access | Small |
| **Q-07** | Expand or replace `styles.ts` usage | Small |
| **P-03** | Optimize CSS bundle size | Small |
| **AC-03** | Touch target sizing enforcement | Medium |

---

## 9. Component-Level Findings

| Component | File | Lines | Worst Severity | Key Issues | Fix Phase |
|-----------|------|-------|----------------|------------|-----------|
| `AgentChatContent` | `components/agent/AgentChatContent.tsx` | 1039 | P1 | Monolithic, 3x duplicated split-pane, keyboard shortcuts | Phase 2 |
| `ProjectAgentStatusBar` | `components/agent/ProjectAgentStatusBar.tsx` | 1137 | P0 | Hardcoded Chinese, 1137 lines, dozens of hardcoded colors, polling | Phase 2 |
| `InputBar` | `components/agent/InputBar.tsx` | 664 | P1 | Hardcoded colors throughout, `getFileIcon` color classes | Phase 2 |
| `TenantChatSidebar` | `components/layout/TenantChatSidebar.tsx` | 848 | P1 | Over 800 lines, duplicates `ConversationSidebar` | Phase 2 |
| `MessageArea` | `components/agent/MessageArea.tsx` | 884 | P2 | Over 800 lines | Phase 5 |
| `TenantHeader` | `components/layout/TenantHeader.tsx` | 600 | P1 | Missing aria-labels on icon buttons | Phase 4 |
| `ConversationSidebar` | `components/agent/ConversationSidebar.tsx` | 714 | P2 | Potentially unused duplicate | Phase 5 |
| `RightPanel` | `components/agent/RightPanel.tsx` | 384 | P2 | Hardcoded colors likely (not fully inventoried) | Phase 3 |
| `EmptyState` | `components/agent/EmptyState.tsx` | 300 | P2 | Hardcoded colors likely | Phase 3 |
| `Resizer` | `components/agent/Resizer.tsx` | 169 | P2 | Hardcoded colors | Phase 2 |
| `LayoutModeSelector` | `components/agent/layout/LayoutModeSelector.tsx` | 131 | P2 | Hardcoded colors, duplicate keyboard shortcuts | Phase 2-3 |
| `AgentChatInputArea` | `components/agent/AgentChatInputArea.tsx` | 96 | — | Clean, well-sized | — |
| `AgentWorkspace` | `pages/tenant/AgentWorkspace.tsx` | 182 | — | Clean entry point | — |
| `index.css` | `src/index.css` | 2177 | P1 | Unused CSS classes, token definitions | Phase 2 |
| `antdTheme.ts` | `theme/antdTheme.ts` | 421 | P1 | Duplicate of CSS tokens | Phase 2 |
| `WorkspaceSidebar` | `components/agent/layout/WorkspaceSidebar.tsx` | 165 | P2 | Orphaned, unused | Phase 3 |
| `TopNavigation` | `components/agent/layout/TopNavigation.tsx` | 149 | P2 | Orphaned, unused | Phase 3 |
| `ChatHistorySidebar` | `components/agent/layout/ChatHistorySidebar.tsx` | 233 | P2 | Orphaned, unused | Phase 3 |

---

## Appendix: Files Analyzed

All files were fully read during the Phase 0 discovery process.

### Core Workspace Components

| File | Lines | Status |
|------|-------|--------|
| `web/src/pages/tenant/AgentWorkspace.tsx` | 182 | Read |
| `web/src/components/agent/AgentChatContent.tsx` | 1039 | Read |
| `web/src/components/agent/MessageArea.tsx` | 884 | Read |
| `web/src/components/agent/AgentChatInputArea.tsx` | 96 | Read |
| `web/src/components/agent/InputBar.tsx` | 664 | Read |
| `web/src/components/agent/EmptyState.tsx` | 300 | Read |
| `web/src/components/agent/RightPanel.tsx` | 384 | Read |
| `web/src/components/agent/ConversationSidebar.tsx` | 714 | Read |
| `web/src/components/agent/MessageBubble.tsx` | 31 | Read |
| `web/src/components/agent/ProjectAgentStatusBar.tsx` | 1137 | Read |
| `web/src/components/agent/Resizer.tsx` | 169 | Read |
| `web/src/components/agent/layout/LayoutModeSelector.tsx` | 131 | Read |
| `web/src/components/agent/styles.ts` | 49 | Read |

### Layout Shell

| File | Lines | Status |
|------|-------|--------|
| `web/src/layouts/TenantLayout.tsx` | 350 | Read |
| `web/src/layouts/AgentLayout.tsx` | 213 | Read |
| `web/src/components/layout/TenantChatSidebar.tsx` | 848 | Read |
| `web/src/components/layout/TenantHeader.tsx` | 600 | Read |

### Design System and Theme

| File | Lines | Status |
|------|-------|--------|
| `web/src/theme/antdTheme.ts` | 421 | Read |
| `web/src/theme/ThemeProvider.tsx` | 48 | Read |
| `web/src/index.css` | 2177 | Read |

### State Management

| File | Lines | Status |
|------|-------|--------|
| `web/src/stores/layoutMode.ts` | 82 | Read |

### Orphaned Design Components (Not Connected to Workspace)

| File | Lines | Status |
|------|-------|--------|
| `web/src/components/agent/layout/WorkspaceSidebar.tsx` | 165 | Read |
| `web/src/components/agent/layout/TopNavigation.tsx` | 149 | Read |
| `web/src/components/agent/layout/ChatHistorySidebar.tsx` | 233 | Read |

### MessageBubble Compound Component

| File | Status |
|------|--------|
| `web/src/components/agent/messageBubble/MessageBubble.tsx` | Read |
| `web/src/components/agent/messageBubble/types.ts` | Read |

---

*End of Phase 1 Audit Report. Proceed to Phase 2 (Normalize) for implementation.*
