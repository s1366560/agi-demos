/**
 * PatternList - Table of workflow patterns
 *
 * Displays patterns with status, name, usage count, and success rate.
 *
 * REACT COMPOSITION PATTERN: Uses configuration objects instead of boolean props
 * for better extensibility and clearer intent.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 */

import React, { memo, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Trash2, Network } from 'lucide-react';

export type PatternStatus = 'preferred' | 'active' | 'deprecated';

export interface PatternDefinition {
  name: string;
  description: string;
  tools: string[];
  steps: Array<{ tool: string; params: Record<string, unknown> }>;
}

export interface WorkflowPattern {
  id: string;
  name: string;
  signature: string;
  status: PatternStatus;
  usageCount: number;
  successRate: number;
  avgRuntime?: number | undefined;
  lastUsed?: string | undefined;
  pattern?: PatternDefinition | undefined;
}

/**
 * View mode configuration for PatternList
 * - 'compact': Shows minimal columns (status, name, success rate)
 * - 'detailed': Shows all columns including usage count
 */
export type PatternListViewMode = 'compact' | 'detailed';

/**
 * Selection policy for pattern list
 * - 'all': All patterns can be selected including deprecated ones
 * - 'active-only': Only active and preferred patterns can be selected
 */
export type PatternListSelectionPolicy = 'all' | 'active-only';

export interface PatternListProps {
  /** List of patterns */
  patterns?: WorkflowPattern[] | undefined;
  /** Currently selected pattern ID */
  selectedId?: string | undefined;
  /** Callback when pattern is selected */
  onSelect?: ((pattern: WorkflowPattern) => void) | undefined;
  /** Callback when pattern is deprecated */
  onDeprecate?: ((patternId: string) => void) | undefined;

  /**
   * View mode configuration
   * Replaces boolean `showAllColumns` prop
   * @default 'detailed'
   */
  viewMode?: PatternListViewMode | undefined;

  /**
   * Selection policy configuration
   * Replaces boolean `allowSelectDeprecated` prop
   * @default 'active-only'
   */
  selectionPolicy?: PatternListSelectionPolicy | undefined;
}

// Memoized status badge component
const StatusBadge = memo(function StatusBadge({ status }: { status: PatternStatus }) {
  const { t } = useTranslation();

  switch (status) {
    case 'preferred':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
          <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
          {t('agent.patternList.status.preferred', { defaultValue: 'Preferred' })}
        </span>
      );
    case 'active':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
          {t('agent.patternList.status.active', { defaultValue: 'Active' })}
        </span>
      );
    case 'deprecated':
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
          {t('agent.patternList.status.deprecated', { defaultValue: 'Deprecated' })}
        </span>
      );
  }
});
StatusBadge.displayName = 'StatusBadge';

// Memoized success rate color function
const getSuccessRateColor = (rate: number): string => {
  if (rate >= 80) return 'bg-emerald-500';
  if (rate >= 60) return 'bg-amber-500';
  return 'bg-red-500';
};

/**
 * PatternList component
 *
 * Configuration objects replace boolean props for better extensibility:
 * - viewMode: 'compact' | 'detailed' (instead of showAllColumns: boolean)
 * - selectionPolicy: 'all' | 'active-only' (instead of allowSelectDeprecated: boolean)
 *
 * @example
 * // Modern usage with configuration objects
 * <PatternList
 *   patterns={patterns}
 *   viewMode="detailed"
 *   selectionPolicy="all"
 *   selectedId={selectedId}
 *   onSelect={(p) => setSelected(p.id)}
 * />
 *
 * @example
 * // Compact view with active-only selection
 * <PatternList
 *   patterns={patterns}
 *   viewMode="compact"
 *   selectionPolicy="active-only"
 * />
 */
export function PatternList({
  patterns = [],
  selectedId,
  onSelect,
  onDeprecate,
  viewMode = 'detailed',
  selectionPolicy = 'active-only',
}: PatternListProps) {
  const { t } = useTranslation();
  const showUsageColumn = viewMode === 'detailed';
  const canSelectDeprecated = selectionPolicy === 'all';

  // Memoize patterns with computed properties to avoid re-computing on every render
  const computedPatterns = useMemo(() => {
    return patterns.map((pattern) => ({
      ...pattern,
      isSelected: pattern.id === selectedId,
      canSelect: pattern.status !== 'deprecated' || canSelectDeprecated,
      isClickable: pattern.status !== 'deprecated' || canSelectDeprecated,
      rowClassName:
        pattern.id === selectedId
          ? 'bg-primary/10 dark:bg-primary/20 cursor-pointer'
          : pattern.status === 'deprecated' && !canSelectDeprecated
            ? 'opacity-50 cursor-not-allowed'
            : 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50',
    }));
  }, [patterns, selectedId, canSelectDeprecated]);

  const handleRowClick = (pattern: WorkflowPattern) => {
    if (pattern.status === 'deprecated' && !canSelectDeprecated) {
      return;
    }
    onSelect?.(pattern);
  };

  const handleDeprecateClick = (e: React.MouseEvent, patternId: string) => {
    e.stopPropagation();
    onDeprecate?.(patternId);
  };

  const handleRowKeyDown = (event: React.KeyboardEvent, pattern: WorkflowPattern) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }
    event.preventDefault();
    handleRowClick(pattern);
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-border-dark dark:bg-surface-dark">
      <div className="min-w-[40rem]">
        {/* Table Header */}
        <div className="grid grid-cols-12 gap-4 px-4 py-3 bg-slate-50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-border-dark text-xs font-semibold text-slate-500 uppercase tracking-wider">
          <div className="col-span-2">
            {t('agent.patternList.columns.status', { defaultValue: 'Status' })}
          </div>
          <div className="col-span-3">
            {t('agent.patternList.columns.patternName', { defaultValue: 'Pattern Name' })}
          </div>
          {showUsageColumn && (
            <div className="col-span-2">
              {t('agent.patternList.columns.usage', { defaultValue: 'Usage' })}
            </div>
          )}
          <div className="col-span-4">
            {t('agent.patternList.columns.successRate', { defaultValue: 'Success Rate' })}
          </div>
          <div className="col-span-1"></div>
        </div>

        {/* Table Body */}
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {computedPatterns.map((pattern) => (
            <div
              key={pattern.id}
              role="button"
              tabIndex={pattern.canSelect ? 0 : -1}
              onClick={() => {
                handleRowClick(pattern);
              }}
              onKeyDown={(event) => {
                handleRowKeyDown(event, pattern);
              }}
              className={`grid w-full grid-cols-12 items-center gap-4 px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${pattern.rowClassName}`}
            >
              {/* Status */}
              <div className="col-span-2">
                <StatusBadge status={pattern.status} />
              </div>

              {/* Name & Signature */}
              <div className="col-span-4 min-w-0">
                <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                  {pattern.name}
                </p>
                <p className="text-xs text-slate-500 truncate font-mono">{pattern.signature}</p>
              </div>

              {/* Usage Count */}
              {showUsageColumn && (
                <div className="col-span-2">
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    {pattern.usageCount.toLocaleString()}
                  </span>
                </div>
              )}

              {/* Success Rate Bar */}
              <div className="col-span-3 flex items-center gap-3">
                <div className="flex-1 h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${getSuccessRateColor(pattern.successRate)} transition-[width] duration-300`}
                    style={{ width: `${String(pattern.successRate)}%` }}
                  />
                </div>
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300 w-12 text-right">
                  {pattern.successRate}%
                </span>
              </div>

              {/* Actions */}
              <div className="col-span-1 flex justify-end">
                <button
                  type="button"
                  onClick={(e) => {
                    handleDeprecateClick(e, pattern.id);
                  }}
                  className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-red-500 transition-colors"
                  title={t('agent.patternList.deletePattern', { defaultValue: 'Delete pattern' })}
                  aria-label={t('agent.patternList.deleteAria', {
                    name: pattern.name,
                    defaultValue: 'Delete {{name}}',
                  })}
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          ))}

          {/* Empty State */}
          {patterns.length === 0 && (
            <div className="px-4 py-12 text-center">
              <Network size={48} className="text-slate-300 dark:text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">
                {t('agent.patternList.empty', { defaultValue: 'No patterns found' })}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Export memoized component
export default memo(PatternList, (prevProps, nextProps) => {
  return (
    prevProps.patterns === nextProps.patterns &&
    prevProps.selectedId === nextProps.selectedId &&
    prevProps.viewMode === nextProps.viewMode &&
    prevProps.selectionPolicy === nextProps.selectionPolicy
  );
});
