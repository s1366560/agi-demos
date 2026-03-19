/**
 * Shared components for timeline event items.
 *
 * Contains TimeBadge, MarkdownRenderer (lazy), and OptionButton
 * used across multiple timeline item sub-components.
 */

import { lazy, Suspense } from 'react';

import { formatDateTime, formatDistanceToNowCN, formatTimeOnly } from '../../../utils/date';
import { safeMarkdownComponents } from '../chat/markdownPlugins';

// Lazy load ReactMarkdown to reduce initial bundle size (bundle-dynamic-imports)
export const MarkdownRenderer = lazy(async () => {
  const [
    { default: ReactMarkdown },
    { default: remarkGfm },
    { default: remarkMath },
    { default: rehypeKatex },
  ] = await Promise.all([
    import('react-markdown'),
    import('remark-gfm'),
    import('remark-math'),
    import('rehype-katex'),
  ]);
  await import('katex/dist/katex.min.css');

  const MarkdownWrapper = ({ children }: { children: string }) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={safeMarkdownComponents}
    >
      {children}
    </ReactMarkdown>
  );

  return { default: MarkdownWrapper };
});

/**
 * Suspense wrapper for MarkdownRenderer
 */
export function MarkdownWithSuspense({ children }: { children: string }) {
  return (
    <Suspense fallback={<div className="text-slate-400">Loading...</div>}>
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  );
}

/**
 * TimeBadge - Natural time display component
 */
export function TimeBadge({ timestamp }: { timestamp: number }) {
  const naturalTime = formatDistanceToNowCN(timestamp);
  const readableTime = formatTimeOnly(timestamp);

  return (
    <span
      className="text-[10px] text-slate-400 dark:text-slate-500 select-none"
      title={formatDateTime(timestamp)}
    >
      {naturalTime} · {readableTime}
    </span>
  );
}

/**
 * Option button component for HITL events
 */
export function OptionButton({
  option,
  isSelected,
  isRecommended,
  onClick,
  disabled,
}: {
  option: { id: string; label: string; description?: string | undefined };
  isSelected?: boolean | undefined;
  isRecommended?: boolean | undefined;
  onClick: () => void;
  disabled?: boolean | undefined;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full text-left p-3 rounded-lg border transition-all
        ${
          isSelected
            ? 'border-primary bg-primary/10 dark:bg-primary/20'
            : 'border-slate-200 dark:border-slate-700 hover:border-primary/50 hover:bg-slate-50 dark:hover:bg-slate-800'
        }
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{option.label}</span>
        {isRecommended && (
          <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
            推荐
          </span>
        )}
      </div>
      {option.description && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{option.description}</p>
      )}
    </button>
  );
}
