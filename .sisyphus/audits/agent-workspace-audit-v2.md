# Agent Workspace Comprehensive Quality Audit Report (v2)

**Date**: 2026-03-24
**Scope**: `web/src/pages/tenant/AgentWorkspace.tsx` and all child components under `web/src/components/agent/` (66 entries, ~25 files read directly, full pattern search across all 66)
**Tech Stack**: React 19.2, TypeScript 5.9, Vite 7.3, Ant Design 6.1, Zustand 5.0, Tailwind 4
**Prior Audit**: `.sisyphus/audits/agent-workspace-audit.md` (v1, same date) -- focused on performance and design. This v2 adds comprehensive accessibility, theming drift, and deeper a11y/responsive findings.

---

## Anti-Patterns Verdict: FAIL (AI Slop Detected)

**Evidence:**

| File | Line | Tell |
|------|------|------|
| `InputBar.tsx` | 1 | Comment: *"Glass-morphism design"* |
| `ConversationSidebar.tsx` | 9 | Comment: *"Clean, modern design with glass morphism"* |
| `index.css` | various | `.glass`, `.glass-light`, `.glass-dark` utility classes; gradient border utilities |
| `EmptyState.tsx` | various | `bg-gradient-to-br from-primary to-primary-600` on avatar/buttons |
| `EmptyState.tsx` | various | Animated gradient blobs, sparkle icons, hover-lift cards -- full AI slop constellation |

**Assessment**: Glass-morphism is a *systemic design choice*, not incidental. The `.glass` utilities in `index.css`, combined with the gradient+blur aesthetic throughout, form an identifiable "AI-generated UI" pattern. The Inter font (configured in `antdTheme.ts`) compounds this. The comments explicitly naming "glass morphism" confirm this was an intentional design direction, but the result is indistinguishable from a Cursor/v0-generated prototype.

**Severity**: Medium. The UI is functional and polished. If brand differentiation matters, this needs a design pass.

**Remediation**: `/normalize` to replace glass-morphism with a distinctive design language; `/bolder` if the goal is visual identity; `/distill` to strip decorative noise.

---

## Executive Summary

The Agent Workspace is a **well-engineered, performance-optimized** chat interface with strong fundamentals -- virtualized rendering (`@tanstack/react-virtual`), `React.memo` with custom comparators, `useShallow` for Zustand selectors, `requestAnimationFrame` throttling, and lazy-loaded Ant Design components. The design token infrastructure is comprehensive (`@theme {}` CSS custom properties, Ant Design token system, `ThemeProvider` syncing Zustand with ConfigProvider).

**The two systemic problems are:**

1. **Theming Drift** (30+ components): Hard-coded hex colors in inline styles and Tailwind arbitrary values bypass the design token system, breaking dark mode parity and making centralized theme changes impossible. The infrastructure exists to do this right -- it's just not enforced.

2. **Inconsistent A11y Application**: Core components (message list, resizer, thinking block, layout selector) have excellent accessibility. Secondary components (drag handles, pinned items, color selectors, modals, inputs) lack basic keyboard/ARIA support. This suggests a11y was applied during initial development but not enforced for all new components.

**By the numbers:**
- **Critical**: 1 (ContextDetailPanel -- 15+ hard-coded colors, zero dark mode)
- **High**: 7 (a11y violations, hard-coded color hotspots, missing landmarks)
- **Medium**: 9 (inconsistent patterns, missing labels, heading hierarchy)
- **Low**: 5 (minor polish items)
- **Positive**: 12 (genuinely good patterns worth preserving)

---

## Detailed Findings

### Critical Severity

#### C1. ContextDetailPanel -- Complete Theming Bypass
**File**: `web/src/components/agent/context/ContextDetailPanel.tsx` (317 lines)
**Issue**: Entirely styled with inline `style={{}}` objects containing 15+ hard-coded hex colors: `#52c41a`, `#1890ff`, `#722ed1`, `#fa8c16`, `#13c2c2`, `#f6ffed`, `#e6f7ff`, `#fff7e6`, `#f9f0ff`, `#666`, `#999`, and more.
**Impact**: This component has **zero dark mode support**. When the user toggles dark mode, this panel renders light-themed content against a dark background -- broken contrast, unreadable text, jarring visual mismatch. It cannot be themed centrally.
**Remediation**: `/normalize` -- replace all inline hex colors with CSS custom properties (`var(--color-*)`) or Tailwind utility classes with `dark:` variants. This is the single highest-impact fix in the entire audit.

---

### High Severity

#### H1. Clickable Divs Without Keyboard Support (WCAG 2.1.1)
**File**: `web/src/components/agent/MessageArea.tsx`, lines 536-546
**Issue**: Pinned message entries are `<div>` elements with `onClick` and `cursor-pointer` but no `role="button"`, no `tabIndex`, no `onKeyDown` handler.
**Impact**: Keyboard-only users cannot activate pinned messages. Screen readers do not announce these as interactive elements.
**Remediation**: `/harden` -- convert to `<button type="button">` or add `role="button" tabIndex={0}` with Enter/Space key handlers.

#### H2. Missing Page Landmark and Skip Navigation (WCAG 2.4.1, 1.3.1)
**File**: `web/src/pages/tenant/AgentWorkspace.tsx`
**Issue**: No `<main>` landmark wrapping the primary content. No skip-to-content link present in agent workspace or layout shell.
**Impact**: Screen reader users have no way to skip past navigation and jump to content. The page lacks structural semantics for landmark navigation.
**Remediation**: `/harden` -- add `<main id="main-content">` wrapper and a visually-hidden skip link.

#### H3. Modal Dialogs Lack Focus Trapping (WCAG 2.4.3)
**Files**: `chat/OnboardingTour.tsx` (lines 186-187), `UnifiedHITLPanel.tsx` (lines 433/451/600/619)
**Issue**: `OnboardingTour` has `aria-modal="true"` and `aria-label` but no focus-trap logic. `UnifiedHITLPanel` uses `autoFocus` on multiple inputs but has no explicit focus containment or focus-restore on close.
**Impact**: When modals are open, Tab key moves focus behind the modal to invisible/obscured elements. Focus is not returned to the trigger element on close.
**Remediation**: `/harden` -- implement focus trap (e.g., `@radix-ui/react-focus-lock` or manual `inert` attribute on background).

#### H4. Hard-Coded Color Constants in 30+ Components (Theming)
**Files** (representative set -- full list from explore agent):
- `ExecutionTimelineChart.tsx` -- `#10b981`, `#ef4444`, `#3b82f6`
- `AgentProgressBar.tsx` -- hex gradient stops
- `TokenUsageChart.tsx` -- color array with 6+ hex values
- `canvas/CanvasPanel.tsx` -- `CHART_COLORS` constant
- `InlineHITLCard.tsx` -- color map (bg/border as hex)
- `CodeExecutorResultCard.tsx` -- success/error bg/border as hex
- `AgentMessageIndicator.tsx` -- `SENT_COLOR` / `RECEIVED_COLOR`
- `UnifiedHITLPanel.tsx` -- icon colors `#1890ff`, `#faad14`, `#52c41a`, `#722ed1`, `#f5222d`
- `SkillExecutionCard.tsx` -- inline bg/border color objects
- `CostTracker.tsx` -- `color: '#999'`, colored bullet spans
- `context/ContextMonitor.tsx` -- compression level color constants
- `sandbox/SandboxTerminal.tsx` -- `bg-[#1e1e1e]`, `border-[#3c3c3c]`
- `sandbox/KasmVNCViewer.tsx` -- `#000000`
- `sandbox/SandboxStatusIndicator.tsx` -- inline hex progress colors
- `sandbox/TerminalImpl.tsx` -- full terminal palette (20+ hex values)
- `ProjectSelector.tsx` -- inline icon color styles
- `BackgroundSubAgentPanel.tsx` -- strokeColor props

**Issue**: Colors defined as local constants or inline styles, bypassing both CSS custom properties and Ant Design tokens.
**Impact**: Colors do not respond to theme changes. Dark mode shows incorrect/clashing colors. Centralized palette changes require editing 30+ files.
**Remediation**: `/normalize` -- create a centralized color token mapping; replace inline hex with `var(--color-*)` or Tailwind semantic utilities.

#### H5. Suppressed A11y Lint Warnings on Drag Handles (WCAG 2.1.1, 4.1.2)
**File**: `web/src/components/agent/AgentChatContent.tsx`, lines 849, 901, 943
**Issue**: Three `biome-ignore lint/a11y/noStaticElementInteractions` suppressions for drag handles. These `<div>` elements have `onMouseDown` handlers but no ARIA roles or keyboard support.
**Impact**: Drag handles are invisible to screen readers and inaccessible to keyboard users.
**Note**: `Resizer.tsx` handles this *correctly* with `role="separator"`, `tabIndex={0}`, `aria-valuenow/min/max`, and `onKeyDown` with arrow key support. The drag handles should follow the same pattern.
**Remediation**: `/harden` -- add `role="separator"`, `tabIndex={0}`, and keyboard handlers following the Resizer.tsx pattern. Remove biome-ignore suppressions.

#### H6. Touch Targets Below WCAG Minimum (WCAG 2.5.8)
**Files**: Multiple toolbar/action buttons across `agent/` components
**Issue**: Toolbar buttons use `h-8 w-8` (32px) which is below the WCAG 2.5.8 target size of 44px. The design system provides a `.touch-target` class (min 44px) and `@media (hover: none)` rules in `index.css`, but these are not consistently applied.
**Impact**: Mobile and motor-impaired users have difficulty activating small targets.
**Remediation**: `/harden` -- apply `.touch-target` class to interactive controls, especially on touch devices.

#### H7. Terminal Palette Hard-Coded (Theming)
**File**: `sandbox/TerminalImpl.tsx`
**Issue**: Full terminal color palette (background, foreground, cursor, selection, ANSI colors) defined as hard-coded hex values.
**Impact**: Terminal colors don't respond to theme changes. Single-file fix with high visual impact.
**Remediation**: `/normalize` -- extract terminal palette to a theme-driven constant.

---

### Medium Severity

#### M1. Icon-Only Buttons Using `title` Instead of `aria-label`
**Files**: `chat/CodeBlock.tsx` (lines 108-117, 153-162), `canvas/CanvasPanel.tsx` (lines 204-211)
**Issue**: Copy/canvas action buttons use `title` attribute for accessible name. `title` is unreliable for screen readers.
**Impact**: Screen reader users may not know what these buttons do.
**Remediation**: `/harden` -- add `aria-label` alongside or instead of `title`.

#### M2. Inputs Missing Accessible Labels (WCAG 1.3.1, 4.1.2)
**Files**:
- `timeline/SubAgentActions.tsx` (lines 58-66) -- redirect input uses only `placeholder`
- `ConversationSidebar.tsx` (lines 159-170) -- new-label input uses `autoFocus` + `placeholder`
- `InputBar.tsx` -- file input and some inline inputs lack explicit labels

**Issue**: `placeholder` is not a replacement for `<label>` or `aria-label`.
**Impact**: Screen readers announce inputs without a label.
**Remediation**: `/harden` -- add `aria-label` to all inputs lacking a visible `<label>`.

#### M3. Heading Hierarchy Inconsistency (WCAG 1.3.1)
**Files**:
- `EmptyState.tsx` line 131 -- `<h1>` in sub-component
- `layout/TopNavigation.tsx` line 53 -- `<h1>{workspaceName}</h1>`
- `chat/IdleState.tsx` line 106 -- `<h1>` hero heading

**Issue**: Multiple components render `<h1>`. When these co-exist on the same page, the document has multiple H1s.
**Impact**: Screen reader users use headings for navigation; multiple H1s make structure ambiguous.
**Remediation**: `/harden` -- designate one component as the page-level H1 source; downgrade others to `<h2>`/`<h3>`.

#### M4. ChatSearch Input Lacks Accessible Label
**File**: `chat/ChatSearch.tsx`, line 173
**Issue**: Search input has `placeholder` but no `aria-label`. Prev/next/close buttons lack `aria-label`.
**Impact**: Screen readers announce "edit text" without context.
**Remediation**: `/harden` -- add `aria-label={t('agent.search.label', 'Search in conversation')}`.

#### M5. Chinese `aria-label` on Navigation Landmark
**File**: `layout/WorkspaceSidebar.tsx`
**Issue**: `<nav aria-label="...">` uses Chinese text (hardcoded). Should use i18n `t()` function.
**Impact**: Non-Chinese screen reader users hear Chinese text for the navigation landmark.
**Remediation**: `/harden` -- replace with `aria-label={t('nav.main', 'Main navigation')}`.

#### M6. Hover-Only Action Buttons (CodeBlock)
**File**: `chat/CodeBlock.tsx`, lines 148-171
**Issue**: When a code block has no language header, copy/canvas buttons are hidden via `opacity-0 group-hover/code:opacity-100`. No `:focus-within` trigger.
**Impact**: Keyboard users cannot discover or use these action buttons.
**Remediation**: `/harden` -- add `group-focus-within/code:opacity-100` to reveal buttons on focus.

#### M7. Direct DOM Manipulation in ChatSearch
**File**: `chat/ChatSearch.tsx`, lines 67-69, 110-142
**Issue**: Uses `document.querySelectorAll('.chat-search-highlight')` for highlight management -- imperative DOM manipulation in a React component.
**Impact**: Fragile; can conflict with React's virtual DOM reconciliation. Not a WCAG violation but a code quality concern.
**Remediation**: Consider React-based approach using state to drive highlight classes.

#### M8. Color Label Buttons Lack Accessible Names
**File**: `ConversationSidebar.tsx`, lines 173-184
**Issue**: Color selector buttons for conversation labels are rendered as colored circles without `aria-label`.
**Impact**: Screen readers announce "button" with no context for color options.
**Remediation**: `/harden` -- add `aria-label={t('color.red', 'Red')}` to each color button.

#### M9. Sandbox Components with Tailwind Arbitrary Hex Values
**Files**: `sandbox/SandboxTerminal.tsx` (`bg-[#1e1e1e]`, `border-[#3c3c3c]`), `sandbox/KasmVNCViewer.tsx` (`#000000`)
**Issue**: Tailwind arbitrary value syntax embeds hex colors in class names, bypassing design tokens.
**Impact**: Colors don't respond to theme changes.
**Remediation**: `/normalize` -- replace with semantic Tailwind classes or `bg-[color:var(--color-surface-dark)]`.

---

### Low Severity

#### L1. Resizer Missing `requestAnimationFrame` Throttling
**File**: `Resizer.tsx`
**Issue**: `mousemove` handler updates state on every event without rAF throttling (unlike `AgentChatContent.tsx` which does throttle).
**Impact**: Potential jank on low-end devices during drag. Not noticeable on modern hardware.
**Remediation**: `/optimize` -- wrap `mousemove` handler in `requestAnimationFrame`.

#### L2. Empty Catch Block in CodeBlock Copy Handler
**File**: `chat/CodeBlock.tsx`, lines 65-67
**Issue**: `catch { // silent fail }` -- clipboard write failure silently swallowed.
**Impact**: Users get no feedback if copy fails.
**Remediation**: `/harden` -- show brief toast on failure.

#### L3. `thinking-content` ID May Collide
**File**: `chat/ThinkingBlock.tsx`, line 177
**Issue**: `id="thinking-content"` is a static ID used in `aria-controls`. If multiple ThinkingBlocks render simultaneously, IDs collide.
**Impact**: `aria-controls` points to wrong element; minor a11y confusion.
**Remediation**: `/harden` -- generate unique IDs with `useId()`.

#### L4. Mixed i18n Coverage
**Files**: Various -- some labels use `t('key')`, others hardcode Chinese or English strings.
**Issue**: Incomplete internationalization.
**Impact**: Users switching languages see a mix.
**Remediation**: `/clarify` -- audit hardcoded strings and move to i18n JSON files.

#### L5. `eslint-disable` Suppressions (Minor)
**Files**: `chat/VirtualizedMessageList.tsx` line 103, `chat/ChatSearch.tsx` lines 64-66, 76-77
**Issue**: ESLint rule suppressions for hooks and setState-in-effect.
**Impact**: Minimal. Patterns are valid for their use cases.
**Remediation**: None required. Document reasons in comments.

---

## Systemic Patterns

### Pattern 1: Theming Drift (30+ components)
The design token infrastructure is **excellent** -- CSS custom properties in `index.css`, Ant Design tokens in `antdTheme.ts`, Tailwind `dark:` variants, `ThemeProvider.tsx` syncing Zustand with ConfigProvider. But 30+ components bypass all of this with inline hex colors and Tailwind arbitrary values. The token system exists but is not enforced.

**Root cause**: No lint rule enforcing token usage. Developers can freely use `style={{ color: '#hex' }}` without friction.
**Fix**: Add ESLint/Biome rule flagging hex/rgb literals in `style` objects. Then run `/normalize` on the top 10 offenders.

### Pattern 2: Inconsistent A11y Application
Core components (MessageArea, VirtualizedMessageList, Resizer, ThinkingBlock, LayoutModeSelector, WorkspaceSidebar) have thoughtful, thorough accessibility. Secondary components (drag handles, pinned items, color selectors, modals, inputs) lack basic keyboard/ARIA support.

**Root cause**: A11y was applied during initial development but not enforced as a pattern for all new components. Biome a11y rules are set to warn (suppressible) rather than error.
**Fix**: Promote Biome a11y rules to errors. Remove existing `biome-ignore` suppressions by fixing underlying issues.

### Pattern 3: Glass-Morphism as Design Language
The `.glass`, `.glass-light`, `.glass-dark` utilities plus `backdrop-blur` usage creates a cohesive but AI-generic aesthetic. This is a design decision, not a bug -- but worth flagging for brand differentiation.

---

## Positive Findings

These patterns are **excellent** and should be preserved as reference implementations:

| # | Pattern | Location | Notes |
|---|---------|----------|-------|
| P1 | Virtualized message list | `VirtualizedMessageList.tsx`, `MessageArea.tsx` | `@tanstack/react-virtual` with `role="log"`, `aria-live="polite"`, auto-scroll with threshold detection |
| P2 | Resizer accessibility | `Resizer.tsx` | `role="separator"`, `tabIndex={0}`, `aria-valuenow/min/max`, arrow key support -- textbook a11y |
| P3 | ThinkingBlock accessibility | `chat/ThinkingBlock.tsx` | `aria-expanded`, `aria-controls`, Enter/Space/Escape keyboard nav, `role="progressbar"` with full ARIA values, custom memo comparator |
| P4 | `useShallow` enforcement | All Zustand stores | Correct `useShallow` usage for multi-value selectors throughout |
| P5 | `React.memo` with custom comparators | `MessageBubble.tsx`, `ThinkingBlock.tsx` | Prevents unnecessary re-renders in the hot path |
| P6 | `requestAnimationFrame` throttling | `AgentChatContent.tsx` | Drag handlers throttled to animation frames |
| P7 | CSS containment utilities | `styles/containment.ts`, `index.css` | `content-visibility: auto`, `contain: layout style paint`, TypeScript-safe helpers |
| P8 | Design token infrastructure | `index.css`, `antdTheme.ts`, `ThemeProvider.tsx` | Comprehensive `@theme {}` block, light/dark Ant Design tokens, CSS custom properties |
| P9 | `prefers-reduced-motion` support | `index.css` | `@media (prefers-reduced-motion: reduce)` with animation overrides |
| P10 | High contrast + forced-colors support | `index.css` | `.high-contrast` class and `@media (forced-colors: active)` |
| P11 | Touch target utilities | `index.css` | `.touch-target` (min 44px) and `@media (hover: none)` responsive rules |
| P12 | `useTransition` for non-urgent updates | `ConversationSidebar.tsx` | React 19 concurrent feature used correctly |

---

## Recommended Actions (Prioritized)

### Priority 1: Critical (Do First)

| Action | Scope | Command | Effort |
|--------|-------|---------|--------|
| Replace all inline hex colors in ContextDetailPanel with design tokens | 1 file, 317 lines | `/normalize` | 1-2 hours |

### Priority 2: High (This Sprint)

| Action | Scope | Command | Effort |
|--------|-------|---------|--------|
| Convert clickable divs to buttons / add ARIA roles + keyboard handlers | MessageArea, AgentChatContent (5 locations) | `/harden` | 2-3 hours |
| Add `<main>` landmark and skip-to-content link | AgentWorkspace or layout shell | `/harden` | 30 min |
| Implement focus trapping in modal dialogs | OnboardingTour, UnifiedHITLPanel | `/harden` | 2-3 hours |
| Centralize chart/status color constants to theme tokens | 8+ files (H4 list) | `/normalize` | 3-4 hours |
| Extract terminal palette to theme-driven config | TerminalImpl.tsx | `/normalize` | 1 hour |
| Add `aria-label` to icon-only buttons using only `title` | CodeBlock, CanvasPanel | `/harden` | 30 min |
| Apply `.touch-target` to small interactive controls | Multiple files | `/harden` | 1-2 hours |

### Priority 3: Medium (Next Sprint)

| Action | Scope | Command | Effort |
|--------|-------|---------|--------|
| Add `aria-label` to all inputs lacking labels | 5-6 files | `/harden` | 1-2 hours |
| Fix heading hierarchy (single H1 per page) | EmptyState, TopNavigation, IdleState | `/harden` | 1 hour |
| Add `group-focus-within` to hover-only buttons | CodeBlock | `/harden` | 15 min |
| Replace Tailwind arbitrary hex in sandbox | SandboxTerminal, KasmVNCViewer | `/normalize` | 1 hour |
| Add color names to label color buttons | ConversationSidebar | `/harden` | 15 min |
| i18n for Chinese aria-label | WorkspaceSidebar | `/harden` | 15 min |
| Add `aria-label` to ChatSearch input and nav buttons | ChatSearch | `/harden` | 15 min |
| Generate unique IDs for ThinkingBlock `aria-controls` | ThinkingBlock | `/harden` | 15 min |

### Priority 4: Low / Nice-to-Have

| Action | Scope | Command | Effort |
|--------|-------|---------|--------|
| Add rAF throttling to Resizer mousemove | Resizer | `/optimize` | 15 min |
| Add clipboard error feedback | CodeBlock | `/harden` | 15 min |
| Add ESLint rule to flag inline hex colors | Config (one-time) | `/normalize` | 1 hour |
| Promote Biome a11y rules from warning to error | Config (one-time) | `/harden` | 30 min |

### Systemic Recommendations

| Action | Command | Impact |
|--------|---------|--------|
| Add Biome/ESLint rule flagging hex/rgb in style objects | `/normalize` | Prevents future theming drift |
| Promote Biome a11y rules to error severity | `/harden` | Catches a11y regressions at lint time |
| Consider replacing glass-morphism with distinctive design | `/bolder` or `/distill` | Brand differentiation |
| Add visual regression tests for dark mode | `/optimize` | Catches theming breaks |

---

## Summary Statistics

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Theming | 1 | 2 | 1 | 0 |
| Accessibility | 0 | 4 | 6 | 2 |
| Performance | 0 | 0 | 1 | 1 |
| Design Quality | 0 | 0 | 0 | 1 |
| Code Quality | 0 | 1 | 1 | 1 |
| **Total** | **1** | **7** | **9** | **5** |

**Total Issues**: 22
**Estimated Fix Effort**: ~3-4 focused sessions (Critical+High first, Medium second, Low third)

---

## Files Audited

### Directly Read (Full Content -- 23 files)
- `web/src/pages/tenant/AgentWorkspace.tsx`
- `web/src/components/agent/AgentChatContent.tsx`
- `web/src/components/agent/context/ContextDetailPanel.tsx`
- `web/src/components/agent/EmptyState.tsx`
- `web/src/components/agent/MessageArea.tsx`
- `web/src/components/agent/AgentChatInputArea.tsx`
- `web/src/components/agent/InputBar.tsx`
- `web/src/components/agent/RightPanel.tsx`
- `web/src/components/agent/messageBubble/MessageBubble.tsx`
- `web/src/components/agent/Resizer.tsx`
- `web/src/components/agent/ConversationSidebar.tsx`
- `web/src/components/agent/styles.ts`
- `web/src/components/agent/layout/LayoutModeSelector.tsx`
- `web/src/components/agent/layout/WorkspaceSidebar.tsx`
- `web/src/components/agent/chat/VirtualizedMessageList.tsx`
- `web/src/components/agent/chat/CodeBlock.tsx`
- `web/src/components/agent/chat/ChatSearch.tsx`
- `web/src/components/agent/chat/ThinkingBlock.tsx`
- `web/src/theme/antdTheme.ts`
- `web/src/theme/ThemeProvider.tsx`
- `web/src/theme/index.ts`
- `web/src/index.css`
- `web/src/styles/containment.ts`

### Searched via Agents (Pattern Matching Across All 66 Entries)
- Full ARIA pattern search across `web/src/components/agent/**`
- Full hex color / inline style search across `web/src/components/agent/**`
- Keyboard handler search across `web/src/components/agent/**`
- Focus management pattern search across `web/src/components/agent/**`

### Not Audited (Out of Scope)
- `web/src/components/agent/comparison/`
- `web/src/components/agent/dashboard/`
- `web/src/components/agent/patterns/`
- `web/src/components/agent/multiAgent/`
- Most files in `web/src/components/agent/chat/` (34 total, 4 read directly)
- Remaining files in `messageBubble/`, `rightPanel/`, `timeline/`, `sandbox/` subdirs

---

*This audit documents issues only. No code changes were made. Use the recommended commands (`/normalize`, `/harden`, `/optimize`, `/polish`, `/distill`, `/bolder`, `/clarify`) to address findings.*
