import React from 'react';
import { Tooltip } from 'antd';
import { Edit3, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function HistoryNavigationRow({
  activeItemRef,
  href,
  isActive,
  primaryTitle,
  contextParts,
  roleLabel,
  timeAgo,
  executionBadge,
  active,
  disabled,
  onRename,
  onDelete,
}: {
  activeItemRef?: React.Ref<HTMLAnchorElement> | undefined;
  href: string;
  isActive: boolean;
  primaryTitle: string;
  contextParts: string[];
  roleLabel?: string | null | undefined;
  timeAgo?: string;
  executionBadge?: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
  onRename?: ((event: React.MouseEvent) => void) | undefined;
  onDelete?: ((event: React.MouseEvent) => void) | undefined;
}) {
  const { t } = useTranslation();
  return (
    <Link
      ref={activeItemRef}
      to={href}
      onClick={(event) => {
        if (disabled) event.preventDefault();
      }}
      aria-current={isActive ? 'page' : undefined}
      className={`
        group relative block w-full p-3 rounded-xl mb-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset
        transition-colors duration-200 border no-underline
        ${
          isActive
            ? 'bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100'
            : 'bg-transparent border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/40'
        }
      `}
    >
      <div className="flex items-start gap-2">
        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className="w-full truncate text-sm font-medium" title={primaryTitle}>
            {primaryTitle}
          </p>
          <div className="mt-1 flex min-w-0 items-center justify-between gap-2 text-xs-plus leading-4 text-slate-400">
            {contextParts.length > 0 ? (
              <div className="flex min-w-0 items-center gap-1.5">
                {contextParts.map((part, index) => (
                  <React.Fragment key={`${part}-${index.toString()}`}>
                    {index > 0 ? (
                      <span className="shrink-0 text-slate-300 dark:text-slate-600">·</span>
                    ) : null}
                    <span
                      className={
                        index === 0 && roleLabel === part
                          ? 'shrink-0 font-semibold uppercase tracking-label'
                          : 'truncate'
                      }
                    >
                      {part}
                    </span>
                  </React.Fragment>
                ))}
              </div>
            ) : (
              <span aria-hidden />
            )}
            <div className="flex shrink-0 items-center gap-1">
              {executionBadge}
              {active ? (
                <Tooltip title={t('agent.sidebar.active', 'Active')}>
                  <span className="inline-flex items-center">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
                    <span className="sr-only">{t('agent.sidebar.active', 'Active')}</span>
                  </span>
                </Tooltip>
              ) : null}
              <span>{timeAgo}</span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div
          className="pointer-events-none absolute right-2 top-1/2 z-10 flex -translate-y-1/2
              items-center gap-0.5 rounded-lg bg-slate-50/95 p-0.5 opacity-0 shadow-sm
              ring-1 ring-slate-200/80 backdrop-blur-sm transition-opacity
              group-hover:pointer-events-auto group-hover:opacity-100
              group-focus-within:pointer-events-auto group-focus-within:opacity-100
              dark:bg-slate-800/95 dark:ring-slate-700/80"
        >
          {onRename ? (
            <button
              type="button"
              aria-label={t('agent.sidebar.rename', 'Rename')}
              title={t('agent.sidebar.rename', 'Rename')}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onRename(event);
              }}
            >
              <Edit3 size={14} />
            </button>
          ) : null}
          {onDelete && (
            <button
              type="button"
              aria-label={t('agent.sidebar.delete', 'Delete')}
              title={t('agent.sidebar.delete', 'Delete')}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-red-500/70 transition-colors hover:bg-red-50 hover:text-red-700 focus-visible:text-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/40 dark:text-red-300/70 dark:hover:bg-red-950/30 dark:hover:text-red-200 dark:focus-visible:text-red-200"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(event);
              }}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
    </Link>
  );
}
