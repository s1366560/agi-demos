/**
 * Shared style constants for Agent chat components.
 *
 * Ensures visual consistency between streaming and historical message rendering.
 */

/**
 * Unified prose classes for all markdown rendering across the chat UI.
 * Single source of truth -- used everywhere markdown content is displayed.
 *
 * Pair with `.memstack-prose` CSS class in index.css for element-level overrides
 * (tables, blockquotes, hr, inline code backgrounds).
 */
export const MARKDOWN_PROSE_CLASSES =
  'memstack-prose max-w-none leading-[1.55] [&_p]:my-1 [&_h1]:mt-3 [&_h1]:mb-1.5 [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:mt-3 [&_h3]:mb-1.5 [&_h4]:mt-3 [&_h4]:mb-1.5 [&_h5]:mt-3 [&_h5]:mb-1.5 [&_h6]:mt-3 [&_h6]:mb-1.5 [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h4]:font-semibold [&_h5]:font-semibold [&_h6]:font-semibold [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_pre]:my-2 [&_pre]:bg-transparent [&_pre]:p-0 [&_a]:text-primary [&_a]:no-underline hover:[&_a]:underline [&_img]:rounded-lg [&_img]:shadow-md [&>p:first-child]:mt-0 [&>p:last-child]:mb-0';

/** @deprecated Use MARKDOWN_PROSE_CLASSES instead */
export const ASSISTANT_PROSE_CLASSES = MARKDOWN_PROSE_CLASSES;

/**
 * Container classes for assistant message bubble.
 * Used by: AssistantMessage, TextEndItem, streaming content display.
 */
export const ASSISTANT_BUBBLE_CLASSES =
  'flex-1 min-w-0 bg-white dark:bg-surface-dark border border-slate-200/55 dark:border-slate-800/55 rounded-lg rounded-tl-sm shadow-[0_1px_2px_rgba(15,23,42,0.025)] px-4 py-2.5';

/**
 * Assistant avatar component classes.
 * Used by: AssistantMessage, streaming content display.
 */
export const ASSISTANT_AVATAR_CLASSES =
  'w-8 h-8 rounded-lg bg-primary/10 ring-1 ring-primary/15 dark:ring-primary/20 flex items-center justify-center shrink-0 mt-0.5';

/**
 * Shared max-width constraint for assistant-side messages and timeline entries.
 * Keeps the left content column readable while using most of the available pane width.
 */
export const MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[96%] md:max-w-[94%] lg:max-w-[92%]';

/**
 * Max-width for dense tool/sub-agent cards that carry structured data.
 */
export const WIDE_MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[98%] md:max-w-[96%] lg:max-w-[94%]';

/**
 * Common layout background for split-pane wrappers.
 * Used by: AgentChatContent layout mode containers.
 */
export const LAYOUT_BG_CLASSES = 'bg-slate-50 dark:bg-slate-950';

/* ============================================================================
 * TYPOGRAPHY ROLES
 *
 * One role, one class string. Sizes resolve to the tokens declared in
 * `index.css` `@theme` (--text-2xs / --text-xs-plus / --text-code), never to
 * arbitrary pixel-literal utilities, so a dense label keeps the same size
 * and leading whatever component renders it.
 * ============================================================================ */

/**
 * Uppercase micro-label for panel section headers, group labels and metadata
 * keys ("EXECUTION", "TOOLS", "ARTIFACTS").
 * Was: 5 sizes x 4 weights x 6 tracking values across the workspace.
 */
export const SECTION_LABEL_CLASSES = 'text-2xs font-semibold uppercase tracking-label';

/* ============================================================================
 * SURFACE / CHROME ROLES
 * ============================================================================ */

/**
 * Panel seam colour shared by every workspace pane edge and divider.
 * Mixing this with the raw `--color-border-*` tokens made the split-pane
 * seam read as a different grey from the panel headers beside it.
 */
export const PANEL_BORDER_CLASSES = 'border-slate-200/60 dark:border-slate-700/50';

/**
 * Header bar of a side panel: title row pinned above a scrolling body.
 */
export const PANEL_HEADER_CLASSES = `flex flex-shrink-0 items-center justify-between gap-2 border-b ${PANEL_BORDER_CLASSES} px-4 py-2`;

/**
 * Body region that owns scrolling inside a flex column.
 * `min-h-0` is required or the pane grows past its container instead of
 * scrolling; `min-w-0` keeps long children from widening the column.
 */
export const PANEL_SCROLL_BODY_CLASSES = 'flex-1 min-h-0 min-w-0 overflow-y-auto';

/* ============================================================================
 * INTERACTION ROLES
 * ============================================================================ */

/**
 * Square icon-only button for workspace chrome (toolbars, status strips,
 * hover-revealed message actions). Same affordance, same recipe everywhere:
 * neutral resting state, single-step hover, visible focus ring, no reflow.
 */
export const ICON_BUTTON_CLASSES =
  'inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-slate-400 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent dark:hover:bg-slate-700 dark:hover:text-slate-300';
