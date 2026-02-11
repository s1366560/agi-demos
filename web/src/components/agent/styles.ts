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
  'memstack-prose prose prose-sm dark:prose-invert max-w-none leading-relaxed prose-p:my-1.5 prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:my-3 prose-pre:bg-transparent prose-pre:p-0 prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-img:rounded-lg prose-img:shadow-md';

/** @deprecated Use MARKDOWN_PROSE_CLASSES instead */
export const ASSISTANT_PROSE_CLASSES = MARKDOWN_PROSE_CLASSES;

/**
 * Container classes for assistant message bubble.
 * Used by: AssistantMessage, TextEndItem, streaming content display.
 */
export const ASSISTANT_BUBBLE_CLASSES =
  'flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-4';

/**
 * Assistant avatar component classes.
 * Used by: AssistantMessage, streaming content display.
 */
export const ASSISTANT_AVATAR_CLASSES =
  'w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5 shadow-sm';
