import { type FC, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { ArrowRight, ChevronDown, ChevronUp } from 'lucide-react';

import { formatDuration } from './subagentUtils';

import type { SubAgentSummary } from '../message/groupTimelineEvents';

export interface SubAgentMiniMapProps {
  summaries: SubAgentSummary[];
  onScrollTo: (startIndex: number) => void;
}

// Simplified version of STATUS_PILL_CLASSES just for the dot indicator
const STATUS_DOT_CLASSES: Record<string, string> = {
  running: 'bg-blue-500',
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  background: 'bg-purple-500',
  queued: 'bg-gray-400',
  killed: 'bg-amber-500',
  steered: 'bg-amber-500',
  depth_limited: 'bg-orange-500',
};

export const SubAgentMiniMap: FC<SubAgentMiniMapProps> = ({ summaries, onScrollTo }) => {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(true);

  if (summaries.length === 0) return null;

  return (
    <div className="absolute top-4 right-4 z-10 w-64 rounded-lg border border-gray-200 bg-white/95 shadow-lg backdrop-blur-sm dark:border-gray-800 dark:bg-gray-900/95 animate-fade-in transition-all duration-200">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between border-b border-gray-100 p-2 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/50"
        onClick={() => {
          setIsExpanded(!isExpanded);
        }}
      >
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
          {t('agent.subagent.minimap_title', 'SubAgent Timeline')}
        </span>
        <span
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          aria-hidden="true"
        >
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>

      {isExpanded && (
        <div className="max-h-[60vh] overflow-y-auto p-1">
          {summaries.map((summary) => (
            <button
              type="button"
              key={`${summary.startIndex}-${summary.subagentId}`}
              className="group flex w-full cursor-pointer items-center justify-between rounded p-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/50"
              onClick={() => {
                onScrollTo(summary.startIndex);
              }}
            >
              <div className="flex items-center gap-2 overflow-hidden">
                <div
                  className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT_CLASSES[summary.status] || 'bg-gray-400'}`}
                  title={summary.status}
                />
                <span className="truncate font-medium text-gray-700 dark:text-gray-300">
                  {summary.name}
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                {summary.executionTimeMs ? (
                  <span>{formatDuration(summary.executionTimeMs)}</span>
                ) : summary.status === 'running' ? (
                  <span className="animate-pulse">running...</span>
                ) : (
                  <span>{summary.status}</span>
                )}
                <ArrowRight
                  size={12}
                  className="opacity-0 transition-opacity group-hover:opacity-100"
                />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
