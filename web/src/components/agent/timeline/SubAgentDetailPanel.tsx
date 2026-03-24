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

  const formatEventDetail = (event: Record<string, unknown>) => {
    const formatInt = (value: number) => String(value);
    switch (event.type) {
      case 'subagent_routed': {
        const confidence =
          typeof event.confidence === 'number'
            ? `${formatInt(Math.round(event.confidence * 100))}%`
            : null;
        const reason = typeof event.reason === 'string' ? event.reason : null;
        return [confidence, reason].filter(Boolean).join(' · ');
      }
      case 'subagent_started': {
        return typeof event.task === 'string' ? event.task : '';
      }
      case 'subagent_session_update': {
        const statusMessage =
          typeof event.statusMessage === 'string'
            ? event.statusMessage
            : typeof event.status_message === 'string'
              ? event.status_message
              : '';
        const tokens =
          typeof event.tokensUsed === 'number'
            ? `${formatTokens(event.tokensUsed)} tokens`
            : typeof event.tokens_used === 'number'
              ? `${formatTokens(event.tokens_used)} tokens`
              : '';
        const toolCalls =
          typeof event.toolCallsCount === 'number'
            ? `${formatInt(event.toolCallsCount)} tools`
            : typeof event.tool_calls_count === 'number'
              ? `${formatInt(event.tool_calls_count)} tools`
              : '';
        return [statusMessage, tokens, toolCalls].filter(Boolean).join(' · ');
      }
      case 'subagent_completed':
      case 'parallel_completed':
      case 'chain_step_completed': {
        const summary = event.summary;
        if (typeof summary === 'string') return summary;
        return '';
      }
      case 'subagent_failed': {
        return typeof event.error === 'string' ? event.error : '';
      }
      default:
        return '';
    }
  };

  const firstEventTimestamp =
    group.events.length > 0 ? (group.events[0]?.timestamp ?? 0) : 0;
  const displayName = group.subagentName || group.subagentId.slice(0, 8);

  return (
    <div className="relative mt-1.5 flex flex-col w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg overflow-hidden transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 animate-in fade-in slide-in-from-bottom-2">
      {/* 1. Header */}
      <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/20">
        <div className="flex min-w-0 items-start gap-2.5">
          <StatusIcon status={group.status} size={16} />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 break-words [overflow-wrap:anywhere]">
              {displayName}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200/50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-400 font-mono">
                {group.subagentId.slice(0, 8)}...
              </span>
              {'modelName' in group && Boolean((group as Record<string, unknown>).modelName) ? (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 break-all">
                  {String((group as Record<string, unknown>).modelName)}
                </span>
              ) : null}
            </div>
          </div>
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
            <p className="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap break-words [overflow-wrap:anywhere] font-mono">
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
            <p className="text-xs text-slate-600 dark:text-slate-400 whitespace-pre-wrap leading-relaxed break-words [overflow-wrap:anywhere]">
              {group.summary}
            </p>
          </div>
        )}

        {/* 2. Timeline Strip */}
        {group.events.length > 0 && (
          <div className="pt-2">
            <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-3 px-1">
              {t('agent.subagent.detail.timeline_title', 'Lifecycle Events')}
            </h4>
            <div className="pl-2">
              {group.events.map((event, i) => {
                const isLast = i === group.events.length - 1;
                const relMs = Math.max(0, event.timestamp - firstEventTimestamp);
                const relTime = relMs > 0 ? `+${formatDuration(relMs)}` : '0ms';
                const eventDetail = formatEventDetail(event as unknown as Record<string, unknown>);

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
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between min-w-0">
                        <div className="text-xs font-medium text-slate-700 dark:text-slate-300 break-words [overflow-wrap:anywhere] pr-2">
                          {formatEventType(event.type)}
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono shrink-0 ml-2">
                          {relTime}
                        </div>
                      </div>
                      {eventDetail && (
                        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed break-words [overflow-wrap:anywhere]">
                          {eventDetail}
                        </p>
                      )}
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
