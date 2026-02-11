import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { GitBranch } from 'lucide-react';

interface BranchIndicatorProps {
  parentTitle?: string;
  onNavigateToParent?: () => void;
}

export const BranchIndicator = memo<BranchIndicatorProps>(
  ({ parentTitle, onNavigateToParent }) => {
    const { t } = useTranslation();
    if (!parentTitle) return null;

    return (
      <div className="flex items-center gap-1.5 px-4 py-2 bg-amber-50/50 dark:bg-amber-900/10 border-b border-amber-200/30 dark:border-amber-800/20 text-xs text-amber-700 dark:text-amber-400">
        <GitBranch size={12} />
        <span>{t('agent.branch.forkedFrom', 'Forked from')}</span>
        {onNavigateToParent ? (
          <button
            onClick={onNavigateToParent}
            className="font-medium underline hover:no-underline"
          >
            {parentTitle}
          </button>
        ) : (
          <span className="font-medium">{parentTitle}</span>
        )}
      </div>
    );
  }
);
BranchIndicator.displayName = 'BranchIndicator';
