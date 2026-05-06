/**
 * TurnPlaceholderRow - rendered in place of the agent block when the user
 * has collapsed a conversation turn. Click to expand again.
 */

import { ChevronDown } from 'lucide-react';
import type { FC } from 'react';

interface TurnPlaceholderRowProps {
  hiddenCount: number;
  onExpand: () => void;
  label?: string;
}

export const TurnPlaceholderRow: FC<TurnPlaceholderRowProps> = ({
  hiddenCount,
  onExpand,
  label,
}) => {
  const text = label ?? `${String(hiddenCount)} item${hiddenCount === 1 ? '' : 's'} hidden`;
  return (
    <div className="flex items-center gap-3 pb-1">
      <div className="w-8 shrink-0" />
      <button
        type="button"
        onClick={onExpand}
        className="flex flex-1 min-w-0 items-center gap-2 rounded-md border border-dashed border-slate-200 bg-slate-50/60 px-3 py-1.5 text-left text-xs text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-100 hover:text-slate-700 dark:border-slate-700/50 dark:bg-slate-800/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        data-testid="turn-placeholder-row"
        aria-label={`Expand turn (${String(hiddenCount)} hidden)`}
      >
        <ChevronDown size={12} className="shrink-0" />
        <span className="truncate">{text}</span>
      </button>
    </div>
  );
};
