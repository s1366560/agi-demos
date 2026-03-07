import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { X, Clock, Zap, XCircle } from 'lucide-react';

import { StatusIcon, ModeIcon } from './SubAgentTimeline';
import { formatDuration, formatTokens } from './subagentUtils';

import type { SubAgentGroup } from './SubAgentTimeline';

export interface SubAgentDetailPanelProps {
  group: SubAgentGroup;
  onClose: () => void;
}

export const SubAgentDetailPanel = memo<SubAgentDetailPanelProps>(({ group, onClose }) => {
  const { t } = useTranslation();

  // Helper for event type formatting
  const formatEventType = (type: string) => {
    return type
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .trim()
      .replace(/\b\w/g, (c) => c.toUpperCase());
  };

  // Get color for timeline dot based on event type
  const getEventDotColor = (type: string) => {
    if (type.includes('error') || type.includes('fail')) return 'bg-red-500';
    if (type.includes('success') || type.includes('complete')) return 'bg-emerald-500';
    if (type.includes('start')) return 'bg-blue-500';
    return 'bg-slate-400';
  };

  const firstEventTimestamp =
    group.events && group.events.length > 0 ? (group.events[0]?.timestamp ?? 0) : 0;

  return (
    <div className="relative flex flex-col w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg overflow-hidden transition-all duration-200 animate-in fade-in slide-in-from-bottom-2">
      {/* 1. Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/20">
        <div className="flex items-center gap-2.5">
          <StatusIcon status={group.status} size={16} />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {group.subagentName}
          </h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200/50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-400 font-mono">
            {group.subagentId.slice(0, 8)}...
          </span>
          {'modelName' in group && Boolean((group as Record<string, unknown>).modelName) ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
              {String((group as Record<string, unknown>).modelName)}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md transition-colors"
          aria-label={t('agent.subagent.detail.close', 'Close')}
        >
          <X size={16} />
        </button>
      </div>

      <div className="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
        {/* 3. Metrics Bar */}
        <div className="flex flex-wrap items-center gap-3">
          {group.mode && (
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 text-xs text-slate-600 dark:text-slate-300">
              <ModeIcon mode={group.mode} size={14} />
              <span className="capitalize">{group.mode}</span>
            </div>
          )}
          {group.executionTimeMs != null && group.executionTimeMs > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 text-xs text-slate-600 dark:text-slate-300">
              <Clock size={14} className="text-slate-400" />
              <span>{formatDuration(group.executionTimeMs)}</span>
            </div>
          )}
          {group.tokensUsed != null && group.tokensUsed > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 text-xs text-slate-600 dark:text-slate-300">
              <Zap size={14} className="text-amber-500" />
              <span>{formatTokens(group.tokensUsed)}</span>
            </div>
          )}
        </div>

        {/* 4. Error Section */}
        {group.error && (
          <div className="p-3 rounded-md bg-red-50 dark:bg-red-950/30 border border-red-200/60 dark:border-red-800/30">
            <h4 className="text-xs font-semibold text-red-700 dark:text-red-400 mb-1 flex items-center gap-1.5">
              <XCircle size={14} />
              {t('agent.subagent.detail.error_title', 'Execution Error')}
            </h4>
            <p className="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap font-mono">
              {group.error}
            </p>
          </div>
        )}

        {/* 5. Summary Section */}
        {group.summary && (
          <div className="p-3 rounded-md bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 shadow-sm">
            <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              {t('agent.subagent.detail.summary_title', 'Execution Summary')}
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-400 whitespace-pre-wrap leading-relaxed">
              {group.summary}
            </p>
          </div>
        )}

        {/* 2. Timeline Strip */}
        {group.events && group.events.length > 0 && (
          <div className="pt-2">
            <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-3 px-1">
              {t('agent.subagent.detail.timeline_title', 'Lifecycle Events')}
            </h4>
            <div className="pl-2">
              {group.events.map((event, i) => {
                const isLast = i === group.events.length - 1;
                const relMs = Math.max(0, event.timestamp - firstEventTimestamp);
                const relTime = relMs > 0 ? `+${formatDuration(relMs)}` : '0ms';

                return (
                  <div key={event.id || i} className="relative flex gap-3 pb-4">
                    {/* Vertical line and dot */}
                    <div className="flex flex-col items-center">
                      <div
                        className={`w-2.5 h-2.5 rounded-full mt-1 ${getEventDotColor(event.type)} relative z-10 shadow-sm border border-white dark:border-slate-900`}
                      />
                      {!isLast && (
                        <div className="w-px h-full bg-slate-200 dark:bg-slate-700 absolute top-3 bottom-0" />
                      )}
                    </div>

                    {/* Content */}
                    <div className="flex-1 flex items-start justify-between min-w-0">
                      <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                        {formatEventType(event.type)}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono shrink-0 ml-2">
                        {relTime}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

SubAgentDetailPanel.displayName = 'SubAgentDetailPanel';
