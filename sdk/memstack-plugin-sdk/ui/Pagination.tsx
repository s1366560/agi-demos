/**
 * Pagination - Shared pagination bar for list pages.
 *
 * Unifies the previously hand-rolled pagination bars in MemoryList,
 * EntitiesList and CommunitiesList (prev/next + page info + optional
 * page-size selector).
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import { ChevronLeft, ChevronRight } from 'lucide-react';

export interface PaginationProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** 0-based current page index. */
  page: number;
  /** Total number of pages (>= 1). */
  totalPages: number;
  onPageChange: (page: number) => void;
  /** Total item count; combined with `pageSize` shows a "start–end of total" summary. */
  totalItems?: number | undefined;
  pageSize?: number | undefined;
  /** When provided together with `onPageSizeChange`, renders a page-size selector. */
  pageSizeOptions?: readonly number[] | undefined;
  onPageSizeChange?: ((pageSize: number) => void) | undefined;
  /** Accessible labels for the prev/next buttons; default to common.actions.previous/next. */
  previousLabel?: string | undefined;
  nextLabel?: string | undefined;
  disabled?: boolean | undefined;
  className?: string | undefined;
}

const navButtonClass =
  'inline-flex h-8 items-center gap-1 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/10 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:focus-visible:ring-slate-50/10';

/**
 * Manual `{{placeholder}}` replacement. Keeps the component compatible with
 * minimal i18n mocks whose `t` returns the defaultValue argument untouched.
 */
function formatTemplate(template: string, values: Record<string, number>): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{{${key}}}`, String(value)),
    template
  );
}

export const Pagination: React.FC<PaginationProps> = ({
  page,
  totalPages,
  onPageChange,
  totalItems,
  pageSize,
  pageSizeOptions,
  onPageSizeChange,
  previousLabel,
  nextLabel,
  disabled = false,
  className = '',
  ...rest
}) => {
  const { t } = useTranslation();
  const safeTotalPages = Math.max(1, totalPages);
  const safePage = Math.min(Math.max(page, 0), safeTotalPages - 1);
  const hasPrev = safePage > 0;
  const hasNext = safePage < safeTotalPages - 1;

  const showRange = totalItems !== undefined && pageSize !== undefined;
  const rangeStart = !showRange || totalItems === 0 ? 0 : safePage * pageSize + 1;
  const rangeEnd = showRange ? Math.min((safePage + 1) * pageSize, totalItems) : 0;

  const summary = showRange
    ? formatTemplate(t('common.pagination.range', '{{start}}–{{end}} of {{total}}'), {
        start: rangeStart,
        end: rangeEnd,
        total: totalItems,
      })
    : formatTemplate(t('common.pagination.page_info', 'Page {{page}} of {{total}}'), {
        page: safePage + 1,
        total: safeTotalPages,
      });

  const rowsPerPageLabel = t('common.pagination.rows_per_page', 'Rows');
  const prevButtonLabel = previousLabel ?? t('common.actions.previous', 'Previous');
  const nextButtonLabel = nextLabel ?? t('common.actions.next', 'Next');

  return (
    <div
      className={`flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between ${className}`}
      {...rest}
    >
      <div className="font-medium">{summary}</div>
      <div className="flex flex-wrap items-center gap-2">
        {pageSizeOptions && onPageSizeChange && pageSize !== undefined && (
          <label className="flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
            <span>{rowsPerPageLabel}</span>
            <select
              value={pageSize}
              onChange={(event) => {
                onPageSizeChange(Number(event.target.value));
              }}
              disabled={disabled}
              className="h-8 rounded border border-slate-200 bg-white px-2 text-sm text-slate-950 outline-none focus:border-slate-950 focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-50 dark:focus:border-slate-400 dark:focus:ring-slate-50/10"
              aria-label={rowsPerPageLabel}
            >
              {pageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          onClick={() => {
            onPageChange(safePage - 1);
          }}
          disabled={disabled || !hasPrev}
          className={navButtonClass}
          aria-label={prevButtonLabel}
          title={prevButtonLabel}
        >
          <ChevronLeft size={16} aria-hidden="true" />
          {prevButtonLabel}
        </button>
        <span className="min-w-16 text-center text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">
          {safePage + 1} / {safeTotalPages}
        </span>
        <button
          type="button"
          onClick={() => {
            onPageChange(safePage + 1);
          }}
          disabled={disabled || !hasNext}
          className={navButtonClass}
          aria-label={nextButtonLabel}
          title={nextButtonLabel}
        >
          {nextButtonLabel}
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};

export default Pagination;
