/**
 * Shared components for timeline event items.
 *
 * Contains TimeBadge, MarkdownRenderer (lazy), and OptionButton
 * used across multiple timeline item sub-components.
 */

import { lazy, Suspense } from 'react';

import { useTranslation } from 'react-i18next';

import { formatDateTime, formatDistanceToNow, formatTimeOnly } from '../../../utils/date';
import { getOptionDescriptionText, getOptionLabelText } from '../../../utils/hitlOptionDisplay';
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
  const { t } = useTranslation();

  return (
    <Suspense
      fallback={
        <div className="text-slate-400">
          {t('components.timelineItems.loadingMarkdown', { defaultValue: 'Loading...' })}
        </div>
      }
    >
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  );
}

/**
 * TimeBadge - Natural time display component with semantic time element
 * WCAG 1.3.1: Uses semantic <time> element with datetime attribute
 */
export function TimeBadge({ timestamp }: { timestamp: number }) {
  const naturalTime = formatDistanceToNow(timestamp);
  const readableTime = formatTimeOnly(timestamp);
  const isoDateTime = new Date(timestamp).toISOString();

  return (
    <time
      dateTime={isoDateTime}
      className="text-2xs text-slate-400 dark:text-slate-500 select-none"
      title={formatDateTime(timestamp)}
    >
      {naturalTime} · {readableTime}
    </time>
  );
}

/**
 * Option button component for HITL events
 * WCAG 2.4.7: Includes visible focus indicator
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
  const { t } = useTranslation();
  const optionLabel = getOptionLabelText(option.label) ?? option.id;
  const optionDescription = getOptionDescriptionText(option.description);

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full text-left p-3 rounded-md border transition-[color,background-color,border-color,box-shadow,opacity,transform]
        focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2
        ${
          isSelected
            ? 'border-primary bg-primary/10 dark:bg-primary/20'
            : 'border-slate-200 dark:border-slate-700 hover:border-primary/50 hover:bg-slate-50 dark:hover:bg-slate-800'
        }
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{optionLabel}</span>
        {isRecommended && (
          <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
            {t('agent.hitl.tag.recommended')}
          </span>
        )}
      </div>
      {optionDescription ? (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{optionDescription}</p>
      ) : null}
    </button>
  );
}
