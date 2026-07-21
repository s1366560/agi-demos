import { memo, useCallback } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { GitBranch, ArrowRight, Clock, Timer, Hash, Loader2 } from 'lucide-react';

import { formatDuration, formatTimestamp, StatusIcon } from './format';

import type {
  DescendantTreeDTO,
  SubAgentRunDTO,
  TraceChainDTO,
  UntracedRunDetailsDTO,
} from '../../../types/multiAgent';
import type { TFunction } from 'i18next';

const STATUS_SURFACE: Record<string, string> = {
  pending: 'bg-slate-50 dark:bg-slate-800',
  running: 'bg-blue-50/70 dark:bg-blue-950/20',
  completed: 'bg-emerald-50/60 dark:bg-emerald-950/20',
  failed: 'bg-red-50/60 dark:bg-red-950/20',
  cancelled: 'bg-amber-50/60 dark:bg-amber-950/20',
};

interface ChainNodeProps {
  run: SubAgentRunDTO;
  isLast: boolean;
  onSelect?: ((run: SubAgentRunDTO) => void) | undefined;
}

const ChainNode: FC<ChainNodeProps> = memo(({ run, isLast, onSelect }) => {
  const statusSurface = STATUS_SURFACE[run.status] ?? 'bg-white dark:bg-slate-800';

  const handleClick = useCallback(() => {
    onSelect?.(run);
  }, [onSelect, run]);

  return (
    <div className="flex items-stretch">
      <div className="flex flex-col items-center w-8 flex-shrink-0">
        <div className="w-8 h-8 rounded-full bg-white dark:bg-slate-800 border-2 border-slate-200 dark:border-slate-600 flex items-center justify-center z-10">
          <StatusIcon status={run.status} />
        </div>
        {!isLast && <div className="w-0.5 flex-1 bg-slate-200 dark:bg-slate-700" />}
      </div>

      <button
        type="button"
        onClick={handleClick}
        className={`flex-1 ml-3 mb-3 p-4 rounded-lg ${statusSurface}
          border border-slate-200 dark:border-slate-700
          hover:shadow-md transition-shadow text-left`}
      >
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {run.subagent_name}
          </span>
          <ArrowRight size={12} className="text-slate-400" />
          <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
            {run.run_id.slice(0, 8)}
          </span>
        </div>

        <p className="text-xs text-slate-600 dark:text-slate-300 line-clamp-2 mb-2">{run.task}</p>

        <div className="flex items-center gap-4 text-2xs text-slate-400 dark:text-slate-500">
          <span className="flex items-center gap-1">
            <Clock size={10} />
            {formatTimestamp(run.started_at)}
            {run.ended_at && (
              <>
                <ArrowRight size={8} />
                {formatTimestamp(run.ended_at)}
              </>
            )}
          </span>
          <span className="flex items-center gap-1">
            <Timer size={10} />
            {formatDuration(run.execution_time_ms)}
          </span>
          {run.tokens_used !== null && (
            <span className="flex items-center gap-1">
              <Hash size={10} />
              {run.tokens_used.toLocaleString()}
            </span>
          )}
        </div>

        {run.error && (
          <p className="mt-2 text-2xs text-red-500 dark:text-red-400 line-clamp-2 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">
            {run.error}
          </p>
        )}

        {run.summary && run.status === 'completed' && (
          <p className="mt-2 text-2xs text-green-600 dark:text-green-400 line-clamp-2 bg-green-50 dark:bg-green-900/20 rounded px-2 py-1">
            {run.summary}
          </p>
        )}

        {run.trace_id && (
          <div className="mt-2 flex items-center gap-1 text-2xs text-slate-400">
            <GitBranch size={10} />
            <span className="font-mono">{run.trace_id.slice(0, 12)}</span>
            {run.parent_span_id && (
              <>
                <span className="mx-1">/</span>
                <span className="font-mono">span:{run.parent_span_id.slice(0, 8)}</span>
              </>
            )}
          </div>
        )}
      </button>
    </div>
  );
});
ChainNode.displayName = 'ChainNode';

interface TraceChainViewProps {
  data: TraceChainDTO | DescendantTreeDTO | UntracedRunDetailsDTO | null;
  isLoading?: boolean;
  onSelectRun?: (run: SubAgentRunDTO) => void;
}

const EmptyChainState: FC = memo(() => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center justify-center p-8 text-center">
      <div className="w-12 h-12 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-3">
        <GitBranch size={24} className="text-slate-400 dark:text-slate-500" />
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t('agent.multiAgent.traceChain.emptyTitle', { defaultValue: 'No chain data' })}
      </p>
      <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
        {t('agent.multiAgent.traceChain.emptyDescription', {
          defaultValue: 'Select a trace to view its execution chain.',
        })}
      </p>
    </div>
  );
});
EmptyChainState.displayName = 'EmptyChainState';

const LoadingState: FC = memo(() => {
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-center p-8">
      <Loader2 size={24} className="text-blue-500 animate-spin motion-reduce:animate-none" />
      <span className="ml-2 text-sm text-slate-500">
        {t('agent.multiAgent.traceChain.loading', { defaultValue: 'Loading trace chain…' })}
      </span>
    </div>
  );
});
LoadingState.displayName = 'LoadingState';

function getChainRuns(
  data: TraceChainDTO | DescendantTreeDTO | UntracedRunDetailsDTO
): SubAgentRunDTO[] {
  if ('runs' in data) return data.runs;
  if ('descendants' in data) return data.descendants;
  return [];
}

function getChainLabel(
  data: TraceChainDTO | DescendantTreeDTO | UntracedRunDetailsDTO,
  t: TFunction
): string {
  if ('trace_id' in data && 'runs' in data) {
    if (data.trace_id === null) {
      return data.runs.length === 1
        ? t('agent.multiAgent.traceChain.runDetails', { defaultValue: 'Run details' })
        : t('agent.multiAgent.traceChain.untracedRuns', { defaultValue: 'Untraced runs' });
    }
    return t('agent.multiAgent.traceChain.traceLabel', {
      id: data.trace_id.slice(0, 12),
      defaultValue: 'Trace: {{id}}',
    });
  }
  if ('parent_run_id' in data) {
    return t('agent.multiAgent.traceChain.descendantsOf', {
      id: data.parent_run_id.slice(0, 12),
      defaultValue: 'Descendants of: {{id}}',
    });
  }
  return t('agent.multiAgent.traceChain.executionChain', { defaultValue: 'Execution Chain' });
}

export const TraceChainView: FC<TraceChainViewProps> = memo(
  ({ data, isLoading = false, onSelectRun }) => {
    const { t } = useTranslation();

    if (isLoading) {
      return <LoadingState />;
    }

    if (!data) {
      return <EmptyChainState />;
    }

    const runs = getChainRuns(data);

    if (runs.length === 0) {
      return <EmptyChainState />;
    }

    const sortedRuns = [...runs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );

    const label = getChainLabel(data, t);
    const totalDuration = sortedRuns.reduce((sum, r) => sum + (r.execution_time_ms ?? 0), 0);
    const totalTokens = sortedRuns.reduce((sum, r) => sum + (r.tokens_used ?? 0), 0);

    return (
      <div>
        <div className="flex items-center justify-between mb-4 px-1">
          <div className="flex items-center gap-2">
            <GitBranch size={16} className="text-blue-500" />
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {label}
            </span>
            <span className="text-xs text-slate-400">
              {t('agent.multiAgent.traceChain.runCount', {
                count: sortedRuns.length,
                defaultValue: '{{count}} runs',
              })}
            </span>
          </div>
          <div className="flex items-center gap-3 text-2xs text-slate-400">
            <span className="flex items-center gap-1">
              <Timer size={10} />
              {formatDuration(totalDuration)}
            </span>
            {totalTokens > 0 && (
              <span className="flex items-center gap-1">
                <Hash size={10} />
                {t('agent.multiAgent.traceChain.tokens', {
                  count: totalTokens,
                  defaultValue: '{{count}} tokens',
                })}
              </span>
            )}
          </div>
        </div>

        <div className="pl-1">
          {sortedRuns.map((run, index) => (
            <ChainNode
              key={run.run_id}
              run={run}
              isLast={index === sortedRuns.length - 1}
              onSelect={onSelectRun}
            />
          ))}
        </div>
      </div>
    );
  }
);
TraceChainView.displayName = 'TraceChainView';
