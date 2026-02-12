/**
 * SubAgentEmptyState - Empty state for SubAgent management page.
 */

import { memo } from 'react';

import { Bot, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface SubAgentEmptyStateProps {
  hasFilters: boolean;
  onCreate: () => void;
}

export const SubAgentEmptyState = memo<SubAgentEmptyStateProps>(({ hasFilters, onCreate }) => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
        <Bot size={28} className="text-slate-300 dark:text-slate-600" />
      </div>
      <h3 className="text-base font-medium text-slate-700 dark:text-slate-300 mb-1">
        {hasFilters
          ? t('tenant.subagents.empty.noResults', 'No matching subagents')
          : t('tenant.subagents.empty.title', 'No subagents yet')}
      </h3>
      <p className="text-sm text-slate-400 dark:text-slate-500 mb-5 max-w-sm">
        {hasFilters
          ? t('tenant.subagents.empty.noResultsHint', 'Try adjusting your search or filters.')
          : t('tenant.subagents.empty.hint', 'Create your first SubAgent to specialize AI tasks.')}
      </p>
      {!hasFilters && (
        <button
          type="button"
          onClick={onCreate}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Plus size={16} />
          {t('tenant.subagents.createNew', 'Create SubAgent')}
        </button>
      )}
    </div>
  );
});

SubAgentEmptyState.displayName = 'SubAgentEmptyState';
