/**
 * SubAgentFilters - Search, status pills, model filter, and sort for SubAgent list.
 */

import { memo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Search, RefreshCw } from 'lucide-react';

export type StatusFilter = 'all' | 'enabled' | 'disabled';
export type SortField = 'name' | 'invocations' | 'success_rate' | 'recent';

interface SubAgentFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (filter: StatusFilter) => void;
  sortField: SortField;
  onSortChange: (sort: SortField) => void;
  onRefresh: () => void;
}

const STATUS_OPTIONS: { value: StatusFilter; labelKey: string; fallback: string }[] = [
  { value: 'all', labelKey: 'tenant.subagents.filter.all', fallback: 'All' },
  { value: 'enabled', labelKey: 'tenant.subagents.filter.enabled', fallback: 'Enabled' },
  { value: 'disabled', labelKey: 'tenant.subagents.filter.disabled', fallback: 'Disabled' },
];

const SORT_OPTIONS: { value: SortField; labelKey: string; fallback: string }[] = [
  { value: 'name', labelKey: 'tenant.subagents.sort.name', fallback: 'Name' },
  { value: 'invocations', labelKey: 'tenant.subagents.sort.invocations', fallback: 'Most Runs' },
  { value: 'success_rate', labelKey: 'tenant.subagents.sort.successRate', fallback: 'Success Rate' },
  { value: 'recent', labelKey: 'tenant.subagents.sort.recent', fallback: 'Recently Used' },
];

export const SubAgentFilters = memo<SubAgentFiltersProps>(
  ({ search, onSearchChange, statusFilter, onStatusFilterChange, sortField, onSortChange, onRefresh }) => {
    const { t } = useTranslation();

    const handleSearchInput = useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => onSearchChange(e.target.value),
      [onSearchChange],
    );

    return (
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
          {/* Search */}
          <div className="relative w-full sm:w-80">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              className="w-full pl-9 pr-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-900 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary"
              placeholder={t('tenant.subagents.filter.searchPlaceholder', 'Search subagents...')}
              value={search}
              onChange={handleSearchInput}
            />
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Status pills */}
            <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-600 p-0.5 bg-slate-50 dark:bg-slate-900">
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onStatusFilterChange(opt.value)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    statusFilter === opt.value
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                      : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
                  }`}
                >
                  {t(opt.labelKey, opt.fallback)}
                </button>
              ))}
            </div>

            {/* Sort */}
            <select
              className="appearance-none text-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2 pr-8 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary/40 cursor-pointer"
              value={sortField}
              onChange={(e) => onSortChange(e.target.value as SortField)}
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {t(opt.labelKey, opt.fallback)}
                </option>
              ))}
            </select>

            {/* Refresh */}
            <button
              type="button"
              onClick={onRefresh}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              aria-label={t('common.refresh', 'Refresh')}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
      </div>
    );
  },
);

SubAgentFilters.displayName = 'SubAgentFilters';
