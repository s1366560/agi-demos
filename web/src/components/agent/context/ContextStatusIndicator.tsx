/**
 * ContextStatusIndicator - Compact context window status for the bottom status bar.
 *
 * Renders an inline token occupancy bar with compression level badge,
 * matching the lucide-react icon style of ProjectAgentStatusBar.
 * Clicking opens the ContextDetailPanel.
 */
import { useMemo } from 'react';
import type { FC } from 'react';

import { Database, Minimize2 } from 'lucide-react';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import { useContextStatus, useContextActions } from '../../../stores/contextStore';

const levelLabels: Record<string, string> = {
  none: '',
  l1_prune: 'L1',
  l2_summarize: 'L2',
  l3_deep_compress: 'L3',
};

function getOccupancyColorClass(pct: number): string {
  if (pct < 60) return 'text-emerald-500';
  if (pct < 80) return 'text-amber-500';
  if (pct < 90) return 'text-orange-500';
  return 'text-red-500';
}

function getBarColorClass(pct: number): string {
  if (pct < 60) return 'bg-emerald-500';
  if (pct < 80) return 'bg-amber-500';
  if (pct < 90) return 'bg-orange-500';
  return 'bg-red-500';
}

function getLevelColorClass(level: string): string {
  switch (level) {
    case 'l1_prune':
      return 'text-amber-600 bg-amber-100 dark:text-amber-400 dark:bg-amber-900/30';
    case 'l2_summarize':
      return 'text-orange-600 bg-orange-100 dark:text-orange-400 dark:bg-orange-900/30';
    case 'l3_deep_compress':
      return 'text-red-600 bg-red-100 dark:text-red-400 dark:bg-red-900/30';
    default:
      return '';
  }
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return String(tokens);
}

export const ContextStatusIndicator: FC = () => {
  const status = useContextStatus();
  const { setDetailExpanded } = useContextActions();

  const occupancy = status?.occupancyPct ?? 0;
  const currentTokens = status?.currentTokens ?? 0;
  const tokenBudget = status?.tokenBudget ?? 128000;
  const compressionLevel = status?.compressionLevel ?? 'none';
  const totalSaved = status?.compressionHistory?.total_tokens_saved ?? 0;
  const fromCache = status?.fromCache ?? false;
  const messagesInSummary = status?.messagesInSummary ?? 0;

  const colorClass = useMemo(() => getOccupancyColorClass(occupancy), [occupancy]);
  const barColorClass = useMemo(() => getBarColorClass(occupancy), [occupancy]);
  const levelLabel = levelLabels[compressionLevel] ?? '';
  const levelColorClass = getLevelColorClass(compressionLevel);

  return (
    <>
      {/* Separator */}
      <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

      <LazyTooltip
        title={
          <div className="space-y-1">
            <div className="font-medium">Context Window</div>
            <div>
              Tokens: {formatTokens(currentTokens)} / {formatTokens(tokenBudget)}
            </div>
            <div>Occupancy: {occupancy.toFixed(1)}%</div>
            {compressionLevel !== 'none' && (
              <div>Compression: {compressionLevel.replace(/_/g, ' ').toUpperCase()}</div>
            )}
            {totalSaved > 0 && <div>Saved: {formatTokens(totalSaved)} tokens</div>}
            {fromCache && messagesInSummary > 0 && (
              <div>Summary: {messagesInSummary} messages cached</div>
            )}
            <div className="text-xs opacity-70 pt-1 border-t border-gray-600 mt-1">
              Click for details
            </div>
          </div>
        }
      >
        <button
          type="button"
          onClick={() => setDetailExpanded(true)}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors cursor-pointer"
        >
          <Database size={11} className={colorClass} />

          {/* Mini progress bar */}
          <div className="w-12 h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${barColorClass}`}
              style={{ width: `${Math.min(occupancy, 100)}%` }}
            />
          </div>

          <span
            className={`font-mono tabular-nums ${colorClass}`}
            style={{ minWidth: 28, fontSize: 11 }}
          >
            {occupancy.toFixed(0)}%
          </span>

          {/* Compression level badge */}
          {levelLabel && (
            <span
              className={`inline-flex items-center gap-0.5 px-1 py-px rounded text-[10px] font-medium ${levelColorClass}`}
            >
              <Minimize2 size={8} />
              {levelLabel}
            </span>
          )}
        </button>
      </LazyTooltip>
    </>
  );
};
