/**
 * Suspense wrapper for MarkdownRenderer
 */

import { Suspense } from 'react';

import { useTranslation } from 'react-i18next';

import { MarkdownRenderer } from './MarkdownRenderer';

export function MarkdownWithSuspense({ children }: { children: string }) {
  const { t } = useTranslation();

  return (
    <Suspense
      fallback={
        <div className="text-slate-400">
          {t('components.timelineItems.loadingMarkdown', { defaultValue: 'Loading…' })}
        </div>
      }
    >
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  );
}
