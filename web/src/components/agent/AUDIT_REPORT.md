# Agent Workspace UI Audit Report

> 历史审计快照，行号可能已漂移。本报告基于 2026-03-24 的代码状态生成；此后组件已演进
> （例如 `InlineHITLCard.tsx` 1196 → 1370 行、`CanvasPanel.tsx` 1768 → 2225 行），引用的
> 行号与文件大小仅作定位参考，请以当前代码为准。关键结论（i18n、a11y、样式系统、硬编码
> 颜色）仍具参考价值，但在动手修复前应重新核对。

**Scope**: `web/src/pages/tenant/AgentWorkspace.tsx` + `web/src/components/agent/` (100+ files)
**Date**: 2026-03-24
**Auditor**: Sisyphus (automated)
**Framework**: React 19.2 + TypeScript 5.9 + Ant Design 6.1 + Zustand 5.0 + Tailwind CSS

---

## Executive Summary

The Agent Workspace is a feature-rich, well-architected chat interface with strong performance patterns (virtualization, lazy loading, memoization) and above-average accessibility in core components. However, it suffers from **pervasive i18n violations** (hard-coded Chinese text in HITL components), **mixed styling systems** (5 approaches coexist), **hard-coded hex colors without dark mode equivalents**, and several **AI design anti-patterns**. The largest risk is the i18n gap in InlineHITLCard.tsx -- a user-facing interactive component rendered entirely in Chinese with no `t()` calls.

---

## Anti-Patterns Verdict (AI Slop Test)

**Score: 6/10 -- BORDERLINE PASS**

| Tell | Status | Location | Notes |
|------|--------|----------|-------|
| Gradient blobs / hero gradients | MINOR | `CanvasPanel.tsx:1546`, `PermissionContent:883` | `bg-gradient-to-br` on decorative icons. Contained to small elements, not page-level. |
| Glassmorphism everywhere | FLAG | `InputBar.tsx` (JSDoc), `ConversationSidebar.tsx` | Both reference "glass morphism" design. InputBar JSDoc: "Glass-morphism design". |
| 3-card suggestion grid | FLAG | `EmptyState.tsx:~200-280` | 3 identical suggestion cards with icon + heading + description. Classic AI slop pattern. |
| Overused font (Inter) | FLAG | `antdTheme.ts` | Primary font is Inter -- explicitly listed as "overused" in design guidelines. |
| Rounded bot avatar | FLAG | `EmptyState.tsx:~170` | `w-16 h-16 rounded-xl bg-primary` with Bot icon. |
| Blue-purple gradients | MINOR | `InlineHITLCard.tsx` icon backgrounds | Subtle, contained to small avatar elements. |
| "AI-assistant-ey" copy | CLEAN | -- | Copy is functional, not promotional. |

**Verdict**: Several AI design tells are present but most are contained to small decorative elements rather than dominating the visual identity. The 3-card grid and Inter font are the most prominent issues.

---

## Findings by Severity

### CRITICAL

#### C1. Hard-Coded Chinese Text in InlineHITLCard.tsx (i18n Bypass)

- **File**: `web/src/components/agent/InlineHITLCard.tsx`
- **Lines**: Throughout (40+ instances)
- **Description**: The entire HITL card system renders in Chinese without any `t()` / `useTranslation()` calls. This includes user-facing interactive elements.
- **Specific strings**:
  - `getHITLTitle()` returns: "Need Clarification", "Need Decision", "Environment Variable Configuration", "Permission Request" (all in Chinese)
  - `formatTimeAgo()` returns: "Just now", "X minutes ago", "X hours ago" (all in Chinese)
  - ClarificationContent: "Custom Answer", "Confirm", "Recommended", "Collapse Details", "View Details"
  - DecisionContent: "Custom Decision", "No preset options...", "Risk Warning", "Confirm Selection"
  - EnvVarContent: "Tool:", "Please enter...", "Save config for next use", "Submit", "Configured", "Done"
  - PermissionContent: "Granted", "Denied", "Risk: Low/Medium/High", "Remember this choice", "Allow", "Deny"
- **Impact**: Non-Chinese-speaking users see untranslatable UI for critical decision-making interactions. HITL cards are the primary human-agent collaboration interface.
- **Fix**: `clarify` skill -- wrap all user-facing strings in `t()` calls with proper i18n keys and English fallbacks.

#### C2. Clickable `<div>` Elements in HITL Cards (A11y)

- **File**: `web/src/components/agent/InlineHITLCard.tsx`
- **Lines**: 326-340 (ClarificationContent options), 528-550 (DecisionContent options), 668-684 (custom decision div)
- **Description**: Option selection uses `<div onClick={...}>` instead of `<button>`, `<label>`, or proper radio/checkbox inputs. These are critical interactive elements where users make decisions.
- **Impact**: Screen reader users cannot interact with HITL option cards. No keyboard focus ring, no role announcement, no Enter/Space activation. Users relying on assistive technology are locked out of the primary decision-making interface.
- **Fix**: Replace `<div onClick>` with `<button type="button">` or `<label>` wrapping actual `<input type="radio">` elements. Add `role="radiogroup"` to the container.

### HIGH

#### H1. Mixed Styling Systems (5 Approaches)

- **Files**: Across all agent components
- **Description**: Five different styling approaches coexist without clear boundaries:
  1. **Tailwind utilities** (dominant) -- `className="text-sm text-slate-500"`
  2. **CSS custom properties** -- `var(--color-primary)`, `resolveThemeColor()`
  3. **Inline style objects** -- `style={{ width: 250 }}`, `style={{ backgroundColor: '#fafafa' }}`
  4. **Hard-coded hex/rgba** -- `'#1890ff'`, `'#e6f7ff'`, `CHART_COLORS`
  5. **Ant Design component props** -- `<Tag color="green">`, `<Button type="primary">`
- **Impact**: Theming changes require updating 5 systems. Dark mode coverage is inconsistent. New developers cannot determine which approach to use. Maintenance cost scales linearly with each new component.
- **Fix**: Run `normalize` skill to consolidate toward Tailwind + CSS variables. Eliminate hard-coded hex values.

#### H2. Hard-Coded Hex Colors Without Dark Mode

- **Files** (with specific hex values):
  - `SkillExecutionCard.tsx`: `#1890ff`, `#e6f7ff`, `#91d5ff`, `#b7eb8f`, `#f6ffed`, `#fff1f0`, `#ffccc7`, `#fffbe6`, `#ffe58f`, `#52c41a`, `#faad14`, `#fafafa`, `#fff1f0`
  - `AgentBindingModal.tsx`: `#ff7a45`, `#52c41a`, `#1890ff` (gradient color map)
  - `SandboxStatusIndicator.tsx`: `#3b82f6`, `#8b5cf6`, `#ef4444`
  - `CanvasPanel.tsx:711`: `CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4']`
  - `TerminalImpl.tsx:64-86`: 20 fallback hex values (acceptable as fallbacks since primary resolution uses CSS tokens)
- **Impact**: These colors render identically in light and dark mode. In dark mode, light backgrounds (`#e6f7ff`, `#fafafa`) clash with dark surroundings. Colors like `#1890ff` (Ant Design v4 blue) are visually inconsistent with the current theme palette.
- **Fix**: Replace with Tailwind classes (`text-blue-500 dark:text-blue-400`) or CSS variable references (`var(--color-primary)`). TerminalImpl.tsx is partially exempt -- it correctly resolves CSS tokens first and only uses hex as fallbacks.

#### H3. Inter as Primary Font

- **File**: `web/src/theme/antdTheme.ts`
- **Description**: Uses `Inter` as the primary font family. Per design guidelines, Inter is explicitly listed as an overused "AI slop" font.
- **Impact**: Contributes to generic "AI product" aesthetic. Reduces brand distinctiveness.
- **Fix**: Replace with a more distinctive system font stack or a less overused typeface. Consider the existing system font fallback chain as the primary.

#### H4. 3-Card Suggestion Grid (EmptyState.tsx)

- **File**: `web/src/components/agent/EmptyState.tsx`
- **Lines**: ~200-280
- **Description**: Three identical suggestion cards arranged in a grid, each with icon + heading + description. This is the canonical "AI chatbot" empty state pattern.
- **Impact**: Indistinguishable from every other AI chat product. Missed opportunity for brand personality.
- **Fix**: Consider asymmetric layout, a single prominent CTA, or contextual suggestions based on project state. Run `bolder` skill for alternatives.

#### H5. dangerouslySetInnerHTML in XlsxPreview

- **File**: `web/src/components/agent/canvas/CanvasPanel.tsx`
- **Line**: 611
- **Description**: `dangerouslySetInnerHTML={{ __html: sheets[activeSheet].html }}` renders SheetJS HTML output directly into the DOM.
- **Impact**: If the XLSX file contains crafted content, it could inject HTML/JS. While SheetJS `sheet_to_html` generally produces safe output, the lack of sanitization is a defense-in-depth gap.
- **Fix**: Sanitize with DOMPurify before rendering: `dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }}`.

### MEDIUM

#### M1. Oversized Components (Maintainability)

| File | Lines | Concern |
|------|-------|---------|
| `CanvasPanel.tsx` | 1768 | 10+ sub-components in one file |
| `InlineHITLCard.tsx` | 1196 | 4 content types + main component |
| `InputBar.tsx` | 1151 | File upload, slash commands, voice, drag-drop |
| `AgentChatContent.tsx` | 1050 | Layout controller with 4 modes |
| `MessageArea.tsx` | 845 | Virtual list + pinned messages |
| `ConversationSidebar.tsx` | 714 | Labels + list + rename + HITL alerts |

- **Impact**: Exceeds 800-line file limit per coding standards. Co-location of 10+ components in CanvasPanel.tsx makes tree-shaking less effective and increases cognitive load.
- **Fix**: Extract sub-components into separate files within their directories. CanvasPanel.tsx sub-components (`CanvasChartPreview`, `CanvasFormPreview`, `XlsxPreview`, `DocxPreview`, etc.) are good extraction candidates.

#### M2. Fixed Width Inline Styles (Responsive)

- **File**: `web/src/components/agent/ProjectSelector.tsx`
- **Lines**: 156, 174, 260
- **Description**: `style={{ width: 250 }}` hard-codes dropdown width in pixels.
- **Impact**: On narrow mobile viewports, 250px dropdowns may overflow or be too cramped. No responsive adaptation.
- **Fix**: Replace with `className="w-full max-w-[250px]"` or responsive Tailwind classes.

#### M3. `document.querySelector` Instead of Refs

- **File**: `web/src/components/agent/AgentChatContent.tsx`
- **Lines**: 374-379, 391-396
- **Description**: Uses `document.querySelector('textarea[data-testid="chat-input"]')` to focus the input, bypassing React's ref system.
- **Impact**: Fragile -- breaks if `data-testid` changes. Slower than ref access. Not compatible with strict CSP or SSR.
- **Fix**: Pass a ref from InputBar and call `.focus()` directly via `useImperativeHandle`.

#### M4. Emoji in Production UI (InlineHITLCard.tsx)

- **File**: `web/src/components/agent/InlineHITLCard.tsx`
- **Line**: 626
- **Description**: Uses `money bag emoji` (`\U0001F4B0`) for cost display in estimated_cost.
- **Impact**: Per coding standards: "No emojis in code, comments, or documentation." Emoji rendering varies across OS/browser. May not be accessible to screen readers.
- **Fix**: Replace with a `DollarSign` icon from lucide-react.

#### M5. Glassmorphism References

- **Files**: `InputBar.tsx` (JSDoc), `ConversationSidebar.tsx`
- **Description**: Both mention "glass morphism" as a design approach.
- **Impact**: Design guidelines warn against "glassmorphism everywhere." If visual effects rely on `backdrop-blur`, they degrade on low-power devices and have no fallback.
- **Fix**: Audit actual visual rendering. If using `backdrop-blur`, ensure `@supports` fallback.

#### M6. CanvasPanel Tab Bar Uses `<div role="tab">` with onClick

- **File**: `web/src/components/agent/canvas/CanvasPanel.tsx`
- **Lines**: 148-168
- **Description**: Tab items use `<div role="tab" tabIndex={0} onClick={...} onKeyDown={...}>`. While this adds keyboard support (`Enter`/`Space`), it lacks the full tablist pattern (`role="tablist"`, `aria-selected`, arrow key navigation).
- **Impact**: Partial ARIA compliance. Screen readers announce tabs but users cannot navigate between them with arrow keys as expected per WAI-ARIA tab pattern.
- **Fix**: Add `role="tablist"` to container, `aria-selected` to each tab, and implement left/right arrow key navigation.

### LOW

#### L1. Inconsistent `aria-*` Coverage

- **Distribution**: 134 `aria-*` usages across 40 files (of ~100 total agent files).
- **Leaders**: `AgentChatContent.tsx` (15), `InputBar.tsx` (9), `ThinkingBlock.tsx` (9), `TopNavigation.tsx` (8), `ChatHistorySidebar.tsx` (8)
- **Lagging**: `SkillExecutionCard.tsx` (1), `AgentGraphView.tsx` (1), `VoiceWaveform.tsx` (1), `AgentStatePill.tsx` (1)
- **Impact**: Inconsistent -- some components are exemplary (ThinkingBlock, MessageArea) while others have minimal accessibility. Core chat flow is well-covered; satellite features lag.
- **Fix**: Prioritize components with user interaction: HITL cards, skill cards, graph views.

#### L2. OnboardingTour Spotlight Hardcoded Overlay

- **File**: `web/src/components/agent/chat/OnboardingTour.tsx`
- **Lines**: 171 (`boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)'`)
- **Description**: Spotlight overlay uses a massive `box-shadow` hack with hard-coded opacity.
- **Impact**: Hard-coded color doesn't respect dark mode preferences. The `9999px` spread is a known technique but not responsive to very large displays.
- **Fix**: Minor -- use CSS variable for overlay color.

#### L3. TerminalImpl Fallback Colors

- **File**: `web/src/components/agent/sandbox/TerminalImpl.tsx`
- **Lines**: 64-86
- **Description**: 20 hard-coded hex fallback values for terminal theme.
- **Impact**: LOW -- These are explicitly fallbacks. The primary path (lines 39-61) uses CSS custom property tokens via `useThemeColors`. Architecture is correct; the hex values are a reasonable safety net.
- **Fix**: No action required. Architecture is sound. Could optionally log a warning if fallback is used.

#### L4. audio Element Fixed Width

- **File**: `web/src/components/agent/canvas/CanvasPanel.tsx`
- **Line**: 399
- **Description**: `<audio ... style={{ width: 320 }}>` uses fixed 320px width.
- **Impact**: On mobile viewports the player may overflow or be too narrow. Minor since audio preview is a secondary feature.
- **Fix**: Replace with `style={{ width: '100%', maxWidth: 320 }}`.

---

## Systemic Issues

### 1. i18n Gap in Agent Components

InlineHITLCard.tsx is the worst offender, but other files also have occasional Chinese strings:
- `InlineHITLCard.tsx`: 40+ hard-coded Chinese strings (CRITICAL)
- `CanvasPanel.tsx`: Uses `t()` consistently -- good reference
- `OnboardingTour.tsx`: Uses `t()` consistently -- good reference
- `EmptyState.tsx`: Uses `t()` consistently -- good reference

**Pattern**: The newer/refactored components use i18n properly. InlineHITLCard appears to have been written before i18n was systematically applied.

### 2. Ant Design v4 Color Residue

Multiple files use Ant Design v4 color palette (`#1890ff`, `#52c41a`, `#faad14`) which differs from the v5/v6 token system. The project uses Ant Design 6.1 with a custom theme (`antdTheme.ts`), but some components bypass the theme entirely.

Affected: `SkillExecutionCard.tsx`, `AgentBindingModal.tsx`.

### 3. Accessibility Split-Brain

Core chat components (MessageArea, ThinkingBlock, AgentChatContent) have excellent a11y:
- `role="log"`, `aria-live="polite"`, `role="separator"`, `aria-expanded`, `aria-controls`
- Keyboard navigation with `Cmd+1/2/3/4` mode switching
- `motion-reduce:animate-none` on animations

But satellite components (HITL cards, skill cards, graph view) have minimal a11y. This suggests a11y was prioritized in the initial core build but not enforced for subsequent features.

---

## Positive Findings

1. **Virtualized rendering** (`@tanstack/react-virtual`) in MessageArea for long conversations
2. **Lazy loading** for heavy components: CodeBlock (hljs), MermaidBlock, TerminalImpl (xterm.js), DocxPreview (docx-preview), XlsxPreview (xlsx)
3. **ThinkingBlock is a11y exemplary**: `aria-expanded`, `aria-controls`, keyboard nav, focus ring, `motion-reduce:animate-none`
4. **Split pane drag handles** have full ARIA: `role="separator"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, `tabIndex`, `aria-label`, keyboard handler
5. **MessageArea** uses `role="log"` + `aria-live="polite"` -- correct for chat interfaces
6. **`useShallow`** pattern consistently followed for Zustand multi-value selectors
7. **`React.memo` + `useCallback` + `useMemo`** extensively applied across all components
8. **OnboardingTour** properly uses `role="dialog"`, `aria-modal="true"`, Escape to close, reduced-motion check
9. **TerminalImpl** correctly resolves CSS custom properties for theme colors with hex fallbacks -- good architecture
10. **CanvasPanel** uses `sandbox` attribute on iframes with appropriate permissions per content type
11. **CanvasTabBar** adds `onKeyDown` handler for keyboard activation (Enter/Space)
12. **`motion-reduce:animate-none`** consistently applied across animated elements

---

## Priority Recommendations

### P0 -- Fix Immediately
1. **InlineHITLCard.tsx i18n**: Wrap all Chinese strings in `t()`. This blocks international deployment.
   ```bash
   # Use clarify skill
   # Target: web/src/components/agent/InlineHITLCard.tsx
   ```
2. **InlineHITLCard.tsx a11y**: Replace `<div onClick>` option cards with `<button>` or radio inputs.

### P1 -- Fix Before Next Release
3. **Hard-coded hex colors**: Replace Ant Design v4 colors in `SkillExecutionCard.tsx`, `AgentBindingModal.tsx`, `SandboxStatusIndicator.tsx` with theme tokens.
   ```bash
   # Use normalize skill
   ```
4. **dangerouslySetInnerHTML**: Add DOMPurify sanitization to XlsxPreview.
5. **CanvasTabBar ARIA**: Add `role="tablist"`, `aria-selected`, arrow key navigation.

### P2 -- Address in Sprint
6. **Split oversized files**: Extract CanvasPanel sub-components, InlineHITLCard content types.
7. **Replace `document.querySelector`** in AgentChatContent with refs.
8. **Fixed-width inline styles**: Convert to responsive Tailwind classes.
9. **Remove emoji** from InlineHITLCard cost display.

### P3 -- Backlog
10. **Font evaluation**: Consider replacing Inter with a more distinctive typeface.
11. **EmptyState redesign**: Move away from 3-card grid pattern.
12. **Glassmorphism audit**: Verify backdrop-blur fallbacks.
13. **Satellite component a11y**: Add ARIA to SkillExecutionCard, AgentGraphView, VoiceWaveform.

---

## Suggested Fix Commands

| Issue | Skill/Command | Target |
|-------|---------------|--------|
| C1: i18n | `clarify` | `InlineHITLCard.tsx` |
| C2: div onClick | `harden` | `InlineHITLCard.tsx` |
| H1: Mixed styles | `normalize` | `components/agent/` |
| H2: Hex colors | `normalize` | `SkillExecutionCard.tsx`, `AgentBindingModal.tsx`, `SandboxStatusIndicator.tsx` |
| H3: Font | `typeset` | `antdTheme.ts` |
| H4: 3-card grid | `bolder` | `EmptyState.tsx` |
| H5: XSS | `harden` | `CanvasPanel.tsx` |
| M1: File size | `extract` | `CanvasPanel.tsx`, `InlineHITLCard.tsx` |
| M6: Tab ARIA | `harden` | `CanvasPanel.tsx` |

---

*Report generated from analysis of 30+ files, 134 aria-* usage points, 40+ hard-coded hex instances, and comprehensive component tree mapping.*
