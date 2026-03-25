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
  'flex-1 min-w-0 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl rounded-tl-sm shadow-sm px-4 py-2.5';

/**
 * Assistant avatar component classes.
 * Used by: AssistantMessage, streaming content display.
 */
export const ASSISTANT_AVATAR_CLASSES =
  'w-8 h-8 rounded-xl bg-primary/10 border border-primary/20 dark:border-primary/25 flex items-center justify-center shrink-0 mt-0.5 shadow-sm';

/**
 * Shared max-width constraint for message bubbles.
 * Used by: UserMessage, AssistantMessage, TextDelta, Thought, ToolExecution, WorkPlan, TextEnd.
 */
export const MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[85%] md:max-w-[75%] lg:max-w-[70%]';

/**
 * Max-width for dense tool/sub-agent cards that carry structured data.
 */
export const WIDE_MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[94%] md:max-w-[88%] lg:max-w-[84%]';

/**
 * Common layout background for split-pane wrappers.
 * Used by: AgentChatContent layout mode containers.
 */
export const LAYOUT_BG_CLASSES = 'bg-slate-50 dark:bg-slate-950';
