import { memo, useCallback } from 'react';
import type { FC } from 'react';

import {
  GitBranch,
  ArrowRight,
  Clock,
  Timer,
  Hash,
  AlertCircle,
  CheckCircle2,
  Loader2,
  XCircle,
} from 'lucide-react';

import type {
  DescendantTreeDTO,
  SubAgentRunDTO,
  TraceChainDTO,
  UntracedRunDetailsDTO,
} from '../../../types/multiAgent';

function formatDuration(ms: number | null): string {
  if (ms === null) return '-';
  if (ms < 1000) return `${String(ms)}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${String(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes)}m ${String(remainingSeconds)}s`;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return '-';
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={16} className="text-green-600 dark:text-green-400" />;
    case 'failed':
      return <AlertCircle size={16} className="text-red-600 dark:text-red-400" />;
    case 'running':
      return (
        <Loader2
          size={16}
          className="text-blue-600 dark:text-blue-400 animate-spin motion-reduce:animate-none"
        />
      );
    case 'cancelled':
      return <XCircle size={16} className="text-amber-600 dark:text-amber-400" />;
    default:
      return <Clock size={16} className="text-slate-400 dark:text-slate-500" />;
  }
}

const STATUS_BG: Record<string, string> = {
  pending: 'border-l-slate-400',
  running: 'border-l-blue-500',
  completed: 'border-l-green-500',
  failed: 'border-l-red-500',
  cancelled: 'border-l-amber-500',
};

interface ChainNodeProps {
  run: SubAgentRunDTO;
  isLast: boolean;
  onSelect?: ((run: SubAgentRunDTO) => void) | undefined;
}

const ChainNode: FC<ChainNodeProps> = memo(({ run, isLast, onSelect }) => {
  const borderColor = STATUS_BG[run.status] ?? 'border-l-slate-300';

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
        className={`flex-1 ml-3 mb-3 p-4 rounded-lg border-l-4 ${borderColor}
          bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700
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

const EmptyChainState: FC = memo(() => (
  <div className="flex flex-col items-center justify-center p-8 text-center">
    <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-3">
      <GitBranch size={24} className="text-slate-400 dark:text-slate-500" />
    </div>
    <p className="text-sm text-slate-500 dark:text-slate-400">No chain data</p>
    <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
      Select a trace to view its execution chain.
    </p>
  </div>
));
EmptyChainState.displayName = 'EmptyChainState';

const LoadingState: FC = memo(() => (
  <div className="flex items-center justify-center p-8">
    <Loader2 size={24} className="text-blue-500 animate-spin motion-reduce:animate-none" />
    <span className="ml-2 text-sm text-slate-500">Loading trace chain...</span>
  </div>
));
LoadingState.displayName = 'LoadingState';

function getChainRuns(data: TraceChainDTO | DescendantTreeDTO | UntracedRunDetailsDTO): SubAgentRunDTO[] {
  if ('runs' in data) return data.runs;
  if ('descendants' in data) return data.descendants;
  return [];
}

function getChainLabel(data: TraceChainDTO | DescendantTreeDTO | UntracedRunDetailsDTO): string {
  if ('trace_id' in data && 'runs' in data) {
    if (data.trace_id === null) {
      return data.runs.length === 1 ? 'Run details' : 'Untraced runs';
    }
    return `Trace: ${data.trace_id.slice(0, 12)}`;
  }
  if ('parent_run_id' in data) {
    return `Descendants of: ${data.parent_run_id.slice(0, 12)}`;
  }
  return 'Execution Chain';
}

export const TraceChainView: FC<TraceChainViewProps> = memo(
  ({ data, isLoading = false, onSelectRun }) => {
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

    const label = getChainLabel(data);
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
              {sortedRuns.length} {sortedRuns.length === 1 ? 'run' : 'runs'}
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
                {totalTokens.toLocaleString()} tokens
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
