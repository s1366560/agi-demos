import { memo, useState, useMemo, useCallback } from 'react';
import type { FC } from 'react';

import {
  Activity,
  ChevronRight,
  ChevronDown,
  Clock,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Timer,
  Hash,
} from 'lucide-react';

import type { SubAgentRunDTO } from '../../../types/multiAgent';

const RUN_STATUS_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  pending: {
    color: 'text-slate-500 dark:text-slate-400',
    bg: 'bg-slate-100 dark:bg-slate-800',
    label: 'Pending',
  },
  running: {
    color: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-900/30',
    label: 'Running',
  },
  completed: {
    color: 'text-green-600 dark:text-green-400',
    bg: 'bg-green-50 dark:bg-green-900/30',
    label: 'Completed',
  },
  failed: {
    color: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-50 dark:bg-red-900/30',
    label: 'Failed',
  },
  cancelled: {
    color: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-50 dark:bg-amber-900/30',
    label: 'Cancelled',
  },
};

const DEFAULT_STATUS_STYLE = {
  color: 'text-slate-500 dark:text-slate-400',
  bg: 'bg-slate-100 dark:bg-slate-800',
  label: 'Unknown',
};

function getStatusStyle(status: string) {
  return RUN_STATUS_STYLES[status] ?? DEFAULT_STATUS_STYLE;
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={14} className="text-green-600 dark:text-green-400" />;
    case 'failed':
      return <AlertCircle size={14} className="text-red-600 dark:text-red-400" />;
    case 'running':
      return (
        <Loader2
          size={14}
          className="text-blue-600 dark:text-blue-400 animate-spin motion-reduce:animate-none"
        />
      );
    case 'cancelled':
      return <AlertCircle size={14} className="text-amber-600 dark:text-amber-400" />;
    default:
      return <Clock size={14} className="text-slate-400 dark:text-slate-500" />;
  }
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '-';
  if (ms < 1000) return `${String(ms)}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${String(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes)}m ${String(remainingSeconds)}s`;
}

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

interface RunItemProps {
  run: SubAgentRunDTO;
  onSelect: (run: SubAgentRunDTO) => void;
  selected: boolean;
}

const RunItem: FC<RunItemProps> = memo(({ run, onSelect, selected }) => {
  const style = getStatusStyle(run.status);

  const handleClick = useCallback(() => {
    onSelect(run);
  }, [onSelect, run]);

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`w-full text-left rounded-lg p-3 transition-colors border ${
        selected
          ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-900/20'
          : 'border-transparent hover:bg-slate-50 dark:hover:bg-slate-800/50'
      }`}
    >
      <div className="flex items-center gap-2">
        <StatusIcon status={run.status} />
        <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate flex-1">
          {run.subagent_name}
        </span>
        <span
          className={`inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium ${style.color} ${style.bg}`}
        >
          {style.label}
        </span>
      </div>

      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">{run.task}</p>

      <div className="mt-2 flex items-center gap-3 text-2xs text-slate-400 dark:text-slate-500">
        <span className="flex items-center gap-1">
          <Clock size={10} />
          {formatTimestamp(run.created_at)}
        </span>
        <span className="flex items-center gap-1">
          <Timer size={10} />
          {formatDuration(run.execution_time_ms)}
        </span>
        {run.tokens_used !== null && (
          <span className="flex items-center gap-1">
            <Hash size={10} />
            {run.tokens_used.toLocaleString()} tokens
          </span>
        )}
      </div>

      {run.error && (
        <p className="mt-1 text-2xs text-red-500 dark:text-red-400 line-clamp-1">{run.error}</p>
      )}

      {run.summary && run.status === 'completed' && (
        <p className="mt-1 text-2xs text-green-600 dark:text-green-400 line-clamp-1">
          {run.summary}
        </p>
      )}
    </button>
  );
});
RunItem.displayName = 'RunItem';

interface TraceGroupProps {
  traceId: string;
  runs: SubAgentRunDTO[];
  selectedRunId: string | null;
  onSelectRun: (run: SubAgentRunDTO) => void;
}

const TraceGroup: FC<TraceGroupProps> = memo(({ traceId, runs, selectedRunId, onSelectRun }) => {
  const [expanded, setExpanded] = useState(true);

  const toggleExpand = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const completedCount = runs.filter((r) => r.status === 'completed').length;
  const failedCount = runs.filter((r) => r.status === 'failed').length;
  const runningCount = runs.filter((r) => r.status === 'running').length;

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={toggleExpand}
        className="w-full flex items-center gap-2 px-4 py-3 bg-slate-50 dark:bg-slate-800/50
            hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        {expanded ? (
          <ChevronDown size={14} className="text-slate-500 flex-shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-slate-500 flex-shrink-0" />
        )}
        <Activity size={14} className="text-blue-500 flex-shrink-0" />
        <span className="text-xs font-mono text-slate-600 dark:text-slate-300 truncate flex-1 text-left">
          {traceId === 'no-trace' ? 'Untraced Runs' : traceId.slice(0, 12)}
        </span>
        <div className="flex items-center gap-2 text-2xs flex-shrink-0">
          <span className="text-slate-400">{runs.length} runs</span>
          {runningCount > 0 && (
            <span className="text-blue-500 font-medium">{runningCount} active</span>
          )}
          {completedCount > 0 && <span className="text-green-500">{completedCount} done</span>}
          {failedCount > 0 && <span className="text-red-500">{failedCount} failed</span>}
        </div>
      </button>

      {expanded && (
        <div className="p-2 space-y-1">
          {runs.map((run) => (
            <RunItem
              key={run.run_id}
              run={run}
              selected={selectedRunId === run.run_id}
              onSelect={onSelectRun}
            />
          ))}
        </div>
      )}
    </div>
  );
});
TraceGroup.displayName = 'TraceGroup';

interface TraceTimelineProps {
  runs: SubAgentRunDTO[];
  selectedRunId?: string | null;
  onSelectRun?: (run: SubAgentRunDTO) => void;
}

const EmptyTraceState: FC = memo(() => (
  <div className="flex flex-col items-center justify-center p-8 text-center">
    <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-3">
      <Activity size={24} className="text-slate-400 dark:text-slate-500" />
    </div>
    <p className="text-sm text-slate-500 dark:text-slate-400">No execution traces</p>
    <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
      SubAgent execution traces will appear here when agents run tasks.
    </p>
  </div>
));
EmptyTraceState.displayName = 'EmptyTraceState';

export const TraceTimeline: FC<TraceTimelineProps> = memo(
  ({ runs, selectedRunId = null, onSelectRun }) => {
    const [internalSelectedId, setInternalSelectedId] = useState<string | null>(null);
    const effectiveSelectedId = selectedRunId ?? internalSelectedId;

    const handleSelectRun = useCallback(
      (run: SubAgentRunDTO) => {
        setInternalSelectedId(run.run_id);
        onSelectRun?.(run);
      },
      [onSelectRun]
    );

    const grouped = useMemo(() => {
      const map = new Map<string, SubAgentRunDTO[]>();
      const sorted = [...runs].sort(
        (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      for (const run of sorted) {
        const key = run.trace_id ?? 'no-trace';
        const list = map.get(key);
        if (list) {
          list.push(run);
        } else {
          map.set(key, [run]);
        }
      }
      return map;
    }, [runs]);

    if (runs.length === 0) {
      return <EmptyTraceState />;
    }

    const traceIds = Array.from(grouped.keys());

    return (
      <div className="space-y-3">
        {traceIds.map((traceId) => {
          const groupRuns = grouped.get(traceId);
          if (!groupRuns) return null;
          return (
            <TraceGroup
              key={traceId}
              traceId={traceId}
              runs={groupRuns}
              selectedRunId={effectiveSelectedId}
              onSelectRun={handleSelectRun}
            />
          );
        })}
      </div>
    );
  }
);
TraceTimeline.displayName = 'TraceTimeline';
