/**
 * SubAgentTimeline - Visual timeline for SubAgent execution events
 *
 * Renders SubAgent routing, execution, and completion in a collapsible card.
 * Supports single execution, parallel groups, and chain pipelines.
 */

import { memo, useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Bot,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Clock,
  Zap,
  GitBranch,
  Layers,
  Rocket,
  Pause,
  Skull,
  Navigation,
  ShieldAlert,
  Info,
} from 'lucide-react';

import { SubAgentDetailPanel } from './SubAgentDetailPanel';
import type { TimelineEvent } from '../../../types/agent';
export interface SubAgentGroup {
  kind: 'subagent';
  subagentId: string;
  subagentName: string;
  status: 'running' | 'success' | 'error' | 'background' | 'queued' | 'killed' | 'steered' | 'depth_limited';
  events: TimelineEvent[];
  startIndex: number;
  confidence?: number | undefined;
  reason?: string | undefined;
  task?: string | undefined;
  summary?: string | undefined;
  error?: string | undefined;
  tokensUsed?: number | undefined;
  executionTimeMs?: number | undefined;
  mode?: 'single' | 'parallel' | 'chain' | undefined;
  parallelInfo?:
    | {
        taskCount: number;
        subtasks: Array<{ subagent_name: string; task: string }>;
        results?: Array<{ subagent_name: string; summary: string; success: boolean }> | undefined;
        totalTimeMs?: number | undefined;
      }
    | undefined;
  chainInfo?:
    | {
        stepCount: number;
        chainName: string;
        steps: Array<{
          index: number;
          name: string;
          subagentName: string;
          summary?: string | undefined;
          success?: boolean | undefined;
          status: 'pending' | 'running' | 'success' | 'error';
        }>;
        totalTimeMs?: number | undefined;
      }
    | undefined;
}

interface SubAgentTimelineProps {
  group: SubAgentGroup;
  isStreaming?: boolean | undefined;
}

const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const formatTokens = (count: number): string => {
  if (count < 1000) return `${count}`;
  return `${(count / 1000).toFixed(1)}k`;
};

const StatusIcon = memo<{ status: string; size?: number | undefined }>(({ status, size = 14 }) => {
  switch (status) {
    case 'running':
      return <Loader2 size={size} className="text-blue-500 animate-spin" />;
    case 'success':
      return <CheckCircle2 size={size} className="text-emerald-500" />;
    case 'error':
      return <XCircle size={size} className="text-red-500" />;
    case 'background':
      return <Rocket size={size} className="text-purple-500" />;
    case 'queued':
      return <Pause size={size} className="text-amber-500" />;
    case 'killed':
      return <Skull size={size} className="text-red-600" />;
    case 'steered':
      return <Navigation size={size} className="text-cyan-500" />;
    case 'depth_limited':
      return <ShieldAlert size={size} className="text-orange-500" />;
    default:
      return <Loader2 size={size} className="text-slate-400 animate-spin" />;
  }
});

StatusIcon.displayName = 'StatusIcon';

const ModeIcon = memo<{ mode?: string | undefined; size?: number | undefined }>(
  ({ mode, size = 14 }) => {
    switch (mode) {
      case 'parallel':
        return <Layers size={size} className="text-indigo-500" />;
      case 'chain':
        return <GitBranch size={size} className="text-amber-500" />;
      default:
        return <Bot size={size} className="text-blue-500" />;
    }
  }
);

ModeIcon.displayName = 'ModeIcon';

// Parallel execution detail view
const ParallelDetail = memo<{ info: SubAgentGroup['parallelInfo'] }>(({ info }) => {
  const { t } = useTranslation();
  if (!info) return null;

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400">
        <Layers size={12} />
        <span>
          {t('agent.subagent.parallel_tasks', 'Parallel execution: {{count}} tasks', {
            count: info.taskCount,
          })}
        </span>
        <span className="text-[9px] px-1 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 font-medium uppercase tracking-wider">
          {t('agent.subagent.parallel_badge', 'Parallel')}
        </span>
      </div>
      <div className={`grid gap-1.5 ${info.taskCount <= 3 ? 'grid-cols-' + info.taskCount : ''}`}>
        {info.subtasks.map((task, i) => {
          const result = info.results?.[i];
          return (
            <div
              key={`parallel-${i}`}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md
                bg-slate-50 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/40"
            >
              {result ? (
                <StatusIcon status={result.success ? 'success' : 'error'} size={12} />
              ) : (
                <Loader2 size={12} className="text-blue-400 animate-spin" />
              )}
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                {task.subagent_name}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400 truncate flex-1">
                {result?.summary || task.task}
              </span>
            </div>
          );
        })}
      </div>
      {info.totalTimeMs != null && (
        <div className="flex items-center gap-1 text-xs text-slate-400">
          <Clock size={10} />
          <span>{formatDuration(info.totalTimeMs)}</span>
        </div>
      )}
      {info.results && (
        <div className="flex items-center gap-3 text-[10px] text-slate-400 mt-1">
          <span className="flex items-center gap-0.5">
            <CheckCircle2 size={9} />
            {info.results.filter(r => r.success).length}/{info.results.length}
          </span>
          <span>{t('agent.subagent.parallel_completed', 'completed')}</span>
        </div>
      )}
    </div>
  );
});

ParallelDetail.displayName = 'ParallelDetail';

// Chain execution detail view
const ChainDetail = memo<{ info: SubAgentGroup['chainInfo'] }>(({ info }) => {
  const { t } = useTranslation();
  if (!info) return null;

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
        <GitBranch size={12} />
        <span>
          {t('agent.subagent.chain_steps', 'Chain: {{name}} ({{count}} steps)', {
            name: info.chainName || 'Pipeline',
            count: info.stepCount,
          })}
        </span>
      </div>
      <div className="relative pl-4 space-y-1">
        {/* Vertical connector line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-0.5 bg-gradient-to-b from-amber-300 to-amber-500 dark:from-amber-600 dark:to-amber-400 rounded-full" />
        {info.steps.map((step) => (
          <div key={`chain-step-${step.index}`} className="relative flex items-start gap-2 py-1">
            {/* Step dot */}
            <span className="text-[9px] font-mono text-slate-400 mr-1 w-3 text-right">{step.index + 1}</span>
            <div className="relative z-10 mt-0.5">
              <StatusIcon status={step.status} size={12} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                  {step.name || step.subagentName}
                </span>
                <span className="text-[10px] text-slate-400">({step.subagentName})</span>
              </div>
              {step.summary && (
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                  {step.summary}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
      {info.totalTimeMs != null && (
        <div className="flex items-center gap-1 text-xs text-slate-400">
          <Clock size={10} />
          <span>{formatDuration(info.totalTimeMs)}</span>
        </div>
      )}
      {info.totalTimeMs != null && info.steps.length > 0 && (
        <div className="flex items-center gap-3 text-[10px] text-slate-400 mt-1">
          <span className="flex items-center gap-0.5">
            <CheckCircle2 size={9} />
            {info.steps.filter(s => s.status === 'success').length}/{info.steps.length}
          </span>
          <span>{t('agent.subagent.chain_completed', 'steps completed')}</span>
        </div>
      )}
    </div>
  );
});

ChainDetail.displayName = 'ChainDetail';

// Main component
export const SubAgentTimeline = memo<SubAgentTimelineProps>(({ group, isStreaming }) => {
  const [expanded, setExpanded] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const { t } = useTranslation();

  const statusBg = useMemo(() => {
    switch (group.status) {
      case 'running':
        return 'bg-blue-50/80 dark:bg-blue-950/30 border-blue-200/60 dark:border-blue-800/40';
      case 'success':
        return 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200/60 dark:border-emerald-800/30';
      case 'error':
        return 'bg-red-50/50 dark:bg-red-950/20 border-red-200/60 dark:border-red-800/30';
      case 'background':
        return 'bg-purple-50/50 dark:bg-purple-950/20 border-purple-200/60 dark:border-purple-800/30';
      case 'queued':
        return 'bg-amber-50/50 dark:bg-amber-950/20 border-amber-200/60 dark:border-amber-800/30';
      case 'killed':
        return 'bg-red-50/70 dark:bg-red-950/30 border-red-300/60 dark:border-red-700/40';
      case 'steered':
        return 'bg-cyan-50/50 dark:bg-cyan-950/20 border-cyan-200/60 dark:border-cyan-800/30';
      case 'depth_limited':
        return 'bg-orange-50/50 dark:bg-orange-950/20 border-orange-200/60 dark:border-orange-800/30';
      default:
        return 'bg-slate-50 dark:bg-slate-800/30 border-slate-200 dark:border-slate-700';
    }
  }, [group.status]);

  const headerLabel = useMemo(() => {
    if (group.status === 'background') {
      return t('agent.subagent.background', 'Background: {{name}}', {
        name: group.subagentName,
      });
    }
    if (group.status === 'queued') {
      return t('agent.subagent.queued', 'Queued: {{name}}', {
        name: group.subagentName,
      });
    }
    if (group.status === 'killed') {
      return t('agent.subagent.killed', 'Killed: {{name}}', {
        name: group.subagentName,
      });
    }
    if (group.status === 'depth_limited') {
      return t('agent.subagent.depth_limited', 'Depth Limited: {{name}}', {
        name: group.subagentName,
      });
    }
    if (group.mode === 'parallel') {
      return t('agent.subagent.parallel', 'Parallel SubAgents');
    }
    if (group.mode === 'chain') {
      return t('agent.subagent.chain', 'Chain: {{name}}', {
        name: group.chainInfo?.chainName || group.subagentName,
      });
    }
    return t('agent.subagent.single', 'SubAgent: {{name}}', {
      name: group.subagentName,
    });
  }, [group, t]);

  return (
    <div className={`rounded-lg border ${statusBg} transition-colors duration-200`}>
      {/* Header */}
      <button
        type="button"
        onClick={() => {
          setExpanded(!expanded);
        }}
        className="w-full flex items-center gap-2 px-3 py-2 text-left
          hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors rounded-t-lg"
      >
        {expanded ? (
          <ChevronDown size={14} className="text-slate-400 shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-slate-400 shrink-0" />
        )}

        <ModeIcon mode={group.mode} size={14} />

        <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate flex-1">
          {headerLabel}
        </span>

        {/* Status badges */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setShowDetail(true); }}
            className="p-0.5 rounded text-slate-400 hover:text-blue-500 transition-colors"
            title={t('agent.subagent.viewDetails', 'View details')}
          >
            <Info size={12} />
          </button>
          {group.confidence != null && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full
              bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400"
            >
              {Math.round(group.confidence * 100)}%
            </span>
          )}
          {group.tokensUsed != null && group.tokensUsed > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full
              bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 flex items-center gap-0.5"
            >
              <Zap size={8} />
              {formatTokens(group.tokensUsed)}
            </span>
          )}
          {group.executionTimeMs != null && group.executionTimeMs > 0 && (
            <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
              <Clock size={9} />
              {formatDuration(group.executionTimeMs)}
            </span>
          )}
          <StatusIcon status={group.status} size={14} />
        </div>
      </button>

      {/* Body */}
      {expanded && (
        <div className="px-3 pb-2.5 space-y-2">
          {/* Task description */}
          {group.task && (
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
              {group.task}
            </p>
          )}

          {/* Routing reason */}
          {group.reason && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500 italic">{group.reason}</p>
          )}

          {/* Parallel detail */}
          {group.mode === 'parallel' && group.parallelInfo && (
            <ParallelDetail info={group.parallelInfo} />
          )}

          {/* Chain detail */}
          {group.mode === 'chain' && group.chainInfo && <ChainDetail info={group.chainInfo} />}

          {/* Summary (on completion) */}
          {group.summary && (
            <div
              className="mt-1 p-2 rounded-md bg-white/60 dark:bg-slate-900/40
              border border-slate-200/40 dark:border-slate-700/30"
            >
              <p className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
                {group.summary}
              </p>
            </div>
          )}

          {/* Error message */}
          {group.error && (
            <div
              className="mt-1 p-2 rounded-md bg-red-50/60 dark:bg-red-950/30
              border border-red-200/40 dark:border-red-800/30"
            >
              <p className="text-xs text-red-600 dark:text-red-400">{group.error}</p>
            </div>
          )}

          {isStreaming && group.status === 'running' && (
            <div className="flex items-center gap-1.5 text-xs text-blue-500">
              <Loader2 size={12} className="animate-spin" />
              <span>{t('agent.subagent.executing', 'Executing...')}</span>
            </div>
          )}
        </div>
      )}
      {showDetail && (
        <SubAgentDetailPanel group={group} onClose={() => setShowDetail(false)} />
      )}
    </div>
  );
});

SubAgentTimeline.displayName = 'SubAgentTimeline';
