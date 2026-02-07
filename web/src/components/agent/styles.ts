/**
 * Shared style constants for Agent chat components.
 *
 * Ensures visual consistency between streaming and historical message rendering.
 */

/**
 * Prose classes for assistant message content (markdown rendering).
 * Used by: AssistantMessage, TextDeltaItem, TextEndItem, streaming content display.
 */
export const ASSISTANT_PROSE_CLASSES =
  'prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed';

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
