/**
 * SubAgentTimeline - Visual timeline for SubAgent execution events
 *
 * Renders SubAgent routing, execution, and completion in a collapsible card.
 * Supports single execution, parallel groups, and chain pipelines.
 *
 * Sprint 1 improvements:
 *  1.1 - Name fallback (name || id slice || unnamed)
 *  1.2 - Status-tinted surface + elevated shadow
 *  1.3 - Status pill with humanized labels
 *  1.4 - Increased padding
 *  1.5 - Humanized error messages
 */

import { memo, useState, useMemo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Steps } from 'antd';
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

import { useAgentV3Store } from '../../../stores/agentV3';

import { SubAgentActions } from './SubAgentActions';
import { SubAgentDetailPanel } from './SubAgentDetailPanel';
import {
  formatDuration,
  formatTokens,
  resolveSubAgentName,
  STATUS_PILL_CLASSES,
  STATUS_LABEL_KEYS,
  STATUS_LABEL_FALLBACKS,
  ERROR_PATTERNS,
} from './subagentUtils';

import type { TimelineEvent } from '../../../types/agent';

export interface SubAgentGroup {
  kind: 'subagent';
  subagentId: string;
  subagentName: string;
  status:
    | 'running'
    | 'success'
    | 'error'
    | 'background'
    | 'queued'
    | 'killed'
    | 'steered'
    | 'depth_limited';
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

// --- Shared sub-components (StatusIcon / ModeIcon remain here for JSX) ---

export const StatusIcon = memo<{ status: string; size?: number | undefined }>(
  ({ status, size = 14 }) => {
    switch (status) {
      case 'running':
        return (
          <Loader2 size={size} className="text-blue-500 animate-spin motion-reduce:animate-none" />
        );
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
        return (
          <Loader2 size={size} className="text-slate-400 animate-spin motion-reduce:animate-none" />
        );
    }
  }
);

StatusIcon.displayName = 'StatusIcon';

export const ModeIcon = memo<{
  mode?: string | undefined;
  size?: number | undefined;
}>(({ mode, size = 14 }) => {
  switch (mode) {
    case 'parallel':
      return <Layers size={size} className="text-indigo-500" />;
    case 'chain':
      return <GitBranch size={size} className="text-amber-500" />;
    default:
      return <Bot size={size} className="text-blue-500" />;
  }
});

ModeIcon.displayName = 'ModeIcon';

// --- Status pill component (1.3) ---

const StatusPill = memo<{ status: string }>(({ status }) => {
  const { t } = useTranslation();
  const key = STATUS_LABEL_KEYS[status] ?? '';
  const fallback = STATUS_LABEL_FALLBACKS[status] ?? status;
  const colorClasses =
    STATUS_PILL_CLASSES[status] ??
    'text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/40';

  return (
    <span
      className={`inline-flex min-h-5 items-center px-2 text-2xs font-medium rounded-full animate-status-pill-in ${colorClasses}`}
    >
      {key ? t(key, fallback) : fallback}
    </span>
  );
});

StatusPill.displayName = 'StatusPill';

// --- Humanized error (1.5) ---

function useHumanizedError(rawError: string | undefined | null): string | null {
  const { t } = useTranslation();
  if (!rawError) return null;

  for (const { pattern, key, fallback } of ERROR_PATTERNS) {
    if (pattern.test(rawError)) {
      return t(key, fallback);
    }
  }
  return rawError;
}

// --- Parallel execution detail view ---

const ParallelDetail = memo<{ info: SubAgentGroup['parallelInfo'] }>(({ info }) => {
  const { t } = useTranslation();
  if (!info) return null;

  const gridCols =
    info.taskCount > 4 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3';

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
      <div className={`grid gap-2 ${gridCols}`}>
        {info.subtasks.map((task, i) => {
          const result = info.results?.[i];
          const isDone = !!result;
          const isSuccess = result?.success;

          let borderClass = 'border-blue-200/60 dark:border-blue-800/40';
          let statusText = t('agent.subagent.parallel_subtaskRunning', 'Running...');

          if (isDone) {
            if (isSuccess) {
              borderClass = 'border-emerald-200/60 dark:border-emerald-800/40';
              statusText = t('agent.subagent.parallel_subtaskDone', 'Done');
            } else {
              borderClass = 'border-red-200/60 dark:border-red-800/40';
              statusText = t('agent.subagent.parallel_subtaskFailed', 'Failed');
            }
          }

          return (
            <div
              key={`parallel-${task.subagent_name}-${task.task}`}
              className={`flex min-w-0 flex-col gap-1.5 p-2.5 rounded-md bg-slate-50 dark:bg-slate-800/50 border ${borderClass}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex min-w-0 items-center gap-1.5">
                  {isDone ? (
                    <StatusIcon status={isSuccess ? 'success' : 'error'} size={12} />
                  ) : (
                    <Loader2
                      size={12}
                      className="text-blue-400 animate-spin motion-reduce:animate-none"
                    />
                  )}
                  <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
                    {task.subagent_name}
                  </span>
                </div>
                <span className="text-2xs text-slate-400 pl-2 shrink-0">{statusText}</span>
              </div>
              <div
                className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 break-words [overflow-wrap:anywhere]"
                title={result?.summary || task.task}
              >
                {result?.summary || task.task}
              </div>
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
        <div className="flex items-center gap-3 text-2xs text-slate-400 mt-1">
          <span className="flex items-center gap-0.5">
            <CheckCircle2 size={9} />
            {info.results.filter((r) => r.success).length}/{info.results.length}
          </span>
          <span>{t('agent.subagent.parallel_completed', 'completed')}</span>
        </div>
      )}
    </div>
  );
});
ParallelDetail.displayName = 'ParallelDetail';

// --- Chain execution detail view ---

const ChainDetail = memo<{ info: SubAgentGroup['chainInfo'] }>(({ info }) => {
  const { t } = useTranslation();
  if (!info) return null;

  const currentStep = info.steps.findIndex((s) => s.status !== 'success');
  const current = currentStep === -1 ? info.steps.length : currentStep;

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400 mb-3">
        <GitBranch size={12} />
        <span>
          {t('agent.subagent.chain_steps', 'Chain: {{name}} ({{count}} steps)', {
            name: info.chainName || 'Pipeline',
            count: info.stepCount,
          })}
        </span>
      </div>

      <Steps
        orientation="vertical"
        size="small"
        current={current}
        className="subagent-chain-steps"
        items={info.steps.map((step) => {
          let stepStatus: 'finish' | 'process' | 'error' | 'wait' = 'wait';
          if (step.status === 'success') stepStatus = 'finish';
          else if (step.status === 'running') stepStatus = 'process';
          else if (step.status === 'error') stepStatus = 'error';

          return {
            title: (
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300 break-words [overflow-wrap:anywhere]">
                {step.name || step.subagentName}{' '}
                <span className="text-2xs text-slate-400 font-normal">({step.subagentName})</span>
              </span>
            ),
            description: step.summary ? (
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 break-words [overflow-wrap:anywhere]">
                {step.summary}
              </div>
            ) : undefined,
            status: stepStatus,
            icon: <StatusIcon status={step.status} size={14} />,
          };
        })}
      />

      {info.totalTimeMs != null && (
        <div className="flex items-center gap-1 text-xs text-slate-400 mt-2">
          <Clock size={10} />
          <span>{formatDuration(info.totalTimeMs)}</span>
        </div>
      )}
      {info.totalTimeMs != null && info.steps.length > 0 && (
        <div className="flex items-center gap-3 text-2xs text-slate-400 mt-1">
          <span className="flex items-center gap-0.5">
            <CheckCircle2 size={9} />
            {info.steps.filter((s) => s.status === 'success').length}/{info.steps.length}
          </span>
          <span>{t('agent.subagent.chain_completed', 'steps completed')}</span>
        </div>
      )}
    </div>
  );
});
ChainDetail.displayName = 'ChainDetail';

// --- Progress phase bar component (2.1) ---

const ProgressPhaseBar = memo<{ group: SubAgentGroup }>(({ group }) => {
  const { t } = useTranslation();

  if (group.status !== 'running') return null;

  const events = group.events;

  let phase = 0;
  let phaseLabel = t('agent.subagent.progress.initializing', 'Initializing...');

  if (events.some((e) => e.type === 'subagent_routed')) {
    phase = 1;
    phaseLabel = t('agent.subagent.progress.routed', 'Routed');
  }
  if (events.some((e) => e.type === 'subagent_started')) {
    phase = 2;
    phaseLabel = t('agent.subagent.progress.started', 'Started');
  }
  if (events.some((e) => e.type === 'subagent_session_update')) {
    phase = 3;
    phaseLabel = t('agent.subagent.progress.executing', 'Executing');
  }

  // Calculate percentage
  let percent = 10;
  if (phase === 1) percent = 33;
  if (phase === 2) percent = 55;
  if (phase === 3) percent = 80;

  let parallelText = null;
  if (group.mode === 'parallel' && group.parallelInfo) {
    const completed = group.parallelInfo.results?.filter((r) => r.success).length || 0;
    const total = group.parallelInfo.taskCount || 0;
    parallelText = t('agent.subagent.progress.parallelTasks', 'Tasks: {{completed}}/{{total}}', {
      completed,
      total,
    });
    if (total > 0) {
      percent = Math.max(percent, Math.min(95, Math.round((completed / total) * 100)));
    }
  }

  return (
    <div className="w-full px-4 pt-2 pb-1">
      <div className="flex justify-between items-center mb-1.5 text-2xs text-slate-500 font-medium">
        <span className="animate-pulse motion-reduce:animate-none">{phaseLabel}</span>
        {parallelText && <span>{parallelText}</span>}
      </div>
      <div className="w-full bg-slate-200/60 dark:bg-slate-700/60 rounded-full h-1 overflow-hidden">
        <div
          className="bg-blue-500 h-1 rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${String(percent)}%` }}
        />
      </div>
    </div>
  );
});

ProgressPhaseBar.displayName = 'ProgressPhaseBar';

// --- Main component ---

export const SubAgentTimeline = memo<SubAgentTimelineProps>(({ group, isStreaming }) => {
  const [expanded, setExpanded] = useState(group.status === 'running');
  const [showDetail, setShowDetail] = useState(false);
  const { t } = useTranslation();
  const activeConversationId = useAgentV3Store((state) => state.activeConversationId);

  // 1.5 - Humanized error
  const humanizedError = useHumanizedError(group.error);

  // Live streaming preview from store
  const subagentPreview = useAgentV3Store((state) => {
    const convId = state.activeConversationId;
    if (!convId) return undefined;
    const convState = state.conversationStates.get(convId);
    return convState?.subagentPreviews.get(group.subagentId);
  });

  // 1.1 - Name fallback
  const displayName = useMemo(
    () =>
      resolveSubAgentName(
        group.subagentName,
        group.subagentId,
        t('agent.subagent.unnamed', 'Unnamed Agent')
      ),
    [group.subagentName, group.subagentId, t]
  );

  // 1.2 - Card classes: status background per status
  const cardClasses = useMemo(() => {
    const pulse = group.status === 'running' ? 'animate-subagent-pulse' : '';

    let bg: string;
    switch (group.status) {
      case 'running':
        bg = 'bg-white dark:bg-slate-900/70 border-blue-200/80 dark:border-blue-800/50';
        break;
      case 'success':
        bg = 'bg-white dark:bg-slate-900/70 border-emerald-200/80 dark:border-emerald-800/40';
        break;
      case 'error':
        bg = 'bg-white dark:bg-slate-900/70 border-red-200/80 dark:border-red-800/40';
        break;
      case 'background':
        bg = 'bg-white dark:bg-slate-900/70 border-purple-200/70 dark:border-purple-800/40';
        break;
      case 'queued':
        bg = 'bg-white dark:bg-slate-900/70 border-amber-200/80 dark:border-amber-800/40';
        break;
      case 'killed':
        bg = 'bg-white dark:bg-slate-900/70 border-red-300/80 dark:border-red-700/50';
        break;
      case 'steered':
        bg = 'bg-white dark:bg-slate-900/70 border-cyan-200/80 dark:border-cyan-800/40';
        break;
      case 'depth_limited':
        bg = 'bg-white dark:bg-slate-900/70 border-orange-200/80 dark:border-orange-800/40';
        break;
      default:
        bg = 'bg-white dark:bg-slate-900/70 border-slate-200 dark:border-slate-700';
    }

    return `rounded-md border ${bg} ${pulse} shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-[border-color,box-shadow] duration-200`;
  }, [group.status]);

  const iconSurfaceClasses = useMemo(() => {
    switch (group.status) {
      case 'running':
        return 'bg-blue-50 text-blue-600 ring-blue-100 dark:bg-blue-950/40 dark:text-blue-300 dark:ring-blue-800/50';
      case 'success':
        return 'bg-emerald-50 text-emerald-600 ring-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800/50';
      case 'error':
      case 'killed':
        return 'bg-red-50 text-red-600 ring-red-100 dark:bg-red-950/40 dark:text-red-300 dark:ring-red-800/50';
      case 'queued':
        return 'bg-amber-50 text-amber-600 ring-amber-100 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-800/50';
      case 'background':
        return 'bg-purple-50 text-purple-600 ring-purple-100 dark:bg-purple-950/40 dark:text-purple-300 dark:ring-purple-800/50';
      case 'steered':
        return 'bg-cyan-50 text-cyan-600 ring-cyan-100 dark:bg-cyan-950/40 dark:text-cyan-300 dark:ring-cyan-800/50';
      case 'depth_limited':
        return 'bg-orange-50 text-orange-600 ring-orange-100 dark:bg-orange-950/40 dark:text-orange-300 dark:ring-orange-800/50';
      default:
        return 'bg-slate-50 text-slate-500 ring-slate-100 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700';
    }
  }, [group.status]);

  // Header label with name fallback applied
  const headerLabel = useMemo(() => {
    if (group.status === 'background') {
      return t('agent.subagent.background', 'Background: {{name}}', {
        name: displayName,
      });
    }
    if (group.status === 'queued') {
      return t('agent.subagent.queued', 'Queued: {{name}}', {
        name: displayName,
      });
    }
    if (group.status === 'killed') {
      return t('agent.subagent.killed', 'Killed: {{name}}', {
        name: displayName,
      });
    }
    if (group.status === 'depth_limited') {
      return t('agent.subagent.depth_limited', 'Depth Limited: {{name}}', {
        name: displayName,
      });
    }
    if (group.mode === 'parallel') {
      return t('agent.subagent.parallel', 'Parallel SubAgents');
    }
    if (group.mode === 'chain') {
      return t('agent.subagent.chain', 'Chain: {{name}}', {
        name: group.chainInfo?.chainName || displayName,
      });
    }
    return t('agent.subagent.single', 'SubAgent: {{name}}', {
      name: displayName,
    });
  }, [group, displayName, t]);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const toggleDetail = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setShowDetail((prev) => !prev);
  }, []);

  const lifecycleSteps = useMemo(() => {
    const hasType = (type: string) => group.events.some((event) => event.type === type);
    return [
      {
        id: 'routed',
        active: hasType('subagent_routed'),
        label: t('agent.subagent.progress.routed', 'Routed'),
      },
      {
        id: 'started',
        active: hasType('subagent_started'),
        label: t('agent.subagent.progress.started', 'Started'),
      },
      {
        id: 'executing',
        active: hasType('subagent_session_update'),
        label: t('agent.subagent.progress.executing', 'Executing'),
      },
      {
        id: 'ended',
        active:
          group.status !== 'running' &&
          group.events.some((event) =>
            [
              'subagent_completed',
              'subagent_failed',
              'subagent_killed',
              'subagent_depth_limited',
              'parallel_completed',
              'chain_completed',
              'background_launched',
            ].includes(event.type)
          ),
        label: t('agent.subagent.detail.timeline_title', 'Lifecycle Events'),
      },
    ];
  }, [group.events, group.status, t]);

  return (
    <div className={cardClasses}>
      <button
        type="button"
        onClick={toggleExpanded}
        className="w-full flex items-center gap-3 px-4 py-3 text-left
          hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors rounded-t-md min-w-0
          focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-1"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-50 text-slate-400 ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>

        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ring-1 ${iconSurfaceClasses}`}
        >
          <ModeIcon mode={group.mode} size={14} />
        </span>

        <div className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold leading-5 text-slate-800 dark:text-slate-100">
            {headerLabel}
          </span>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex min-w-0 items-center gap-1">
              <Bot size={9} />
              <span className="truncate max-w-[160px]">{displayName}</span>
            </span>
            <span className="inline-flex items-center">
              {group.events.length} {t('agent.subagent.detail.timeline_title', 'Lifecycle Events')}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2 max-w-[48%]">
          {group.confidence != null && (
            <span
              className="text-2xs px-2 py-0.5 rounded-full
              bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400"
            >
              {Math.round(group.confidence * 100)}%
            </span>
          )}
          {group.tokensUsed != null && group.tokensUsed > 0 && (
            <span
              className="text-2xs px-2 py-0.5 rounded-full
              bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 flex items-center gap-0.5"
            >
              <Zap size={8} />
              {formatTokens(group.tokensUsed)}
            </span>
          )}
          {group.executionTimeMs != null && group.executionTimeMs > 0 && (
            <span className="text-2xs text-slate-400 flex items-center gap-0.5 shrink-0">
              <Clock size={9} />
              {formatDuration(group.executionTimeMs)}
            </span>
          )}
          <StatusPill status={group.status} />
        </div>
      </button>

      {/* 2.1 - Progress Phase Bar */}
      {group.status === 'running' && <ProgressPhaseBar group={group} />}

      {/* Live streaming preview */}
      {group.status === 'running' && subagentPreview && (
        <div className="mx-4 mt-2 rounded-md bg-slate-50 dark:bg-slate-800/50 px-3 py-2 text-xs text-slate-600 dark:text-slate-400 font-mono leading-relaxed animate-fade-in border border-slate-200/70 dark:border-slate-700/60">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
            <span className="text-slate-500 dark:text-slate-500 text-2xs uppercase tracking-wider font-sans">
              {t('agent.subagent.live_preview')}
            </span>
          </div>
          <div className="line-clamp-3 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {subagentPreview}
          </div>
        </div>
      )}

      {/* Body — 1.4: px-4 pb-3.5 (was px-3 pb-2.5), gap-2.5 (was gap/space-y-2) */}
      {expanded && (
        <div className="px-4 pb-3.5 space-y-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {lifecycleSteps.map((step) => (
              <span
                key={step.id}
                className={`text-2xs px-2 py-0.5 rounded-full border ${
                  step.active
                    ? 'border-primary/30 bg-primary/10 text-primary dark:border-primary/40 dark:bg-primary/20'
                    : 'border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-800/40 text-slate-400'
                }`}
              >
                {step.label}
              </span>
            ))}
          </div>

          {/* Task description */}
          {group.task && (
            <p className="max-w-[76ch] text-xs text-slate-600 dark:text-slate-400 leading-relaxed break-words [overflow-wrap:anywhere]">
              {group.task}
            </p>
          )}

          {/* Routing reason */}
          {group.reason && (
            <p className="max-w-[76ch] text-xs-plus text-slate-400 dark:text-slate-500 italic break-words [overflow-wrap:anywhere]">
              {group.reason}
            </p>
          )}

          {/* Parallel detail */}
          {group.mode === 'parallel' && group.parallelInfo && (
            <ParallelDetail info={group.parallelInfo} />
          )}

          {/* Chain detail */}
          {group.mode === 'chain' && group.chainInfo && <ChainDetail info={group.chainInfo} />}

          {/* Summary (on completion) — 2.3 distinct output framing (quote block) & 2.6 Animated Status Transitions */}
          {group.summary && (
            <div className="mt-1 animate-fade-in rounded-md border border-slate-200/80 bg-slate-50/70 px-3 py-2.5 dark:border-slate-700/70 dark:bg-slate-800/40">
              <p className="max-w-[76ch] text-xs text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                {group.summary}
              </p>
            </div>
          )}

          {/* Error message — 1.5: humanized error */}
          {humanizedError && (
            <div
              className="mt-1 p-2.5 rounded-md bg-red-50/60 dark:bg-red-950/30
              border border-red-200/40 dark:border-red-800/30"
            >
              <p className="text-xs text-red-600 dark:text-red-400 break-words [overflow-wrap:anywhere]">
                {humanizedError}
              </p>
            </div>
          )}

          {isStreaming && group.status === 'running' && (
            <div className="flex items-center gap-1.5 text-xs text-blue-500">
              <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
              <span>{t('agent.subagent.executing', 'Executing...')}</span>
            </div>
          )}

          {group.status === 'running' && activeConversationId && (
            <SubAgentActions subagentId={group.subagentId} conversationId={activeConversationId} />
          )}

          {/* 2.2 - Inline Detail Panel refinement (moved to bottom of body) */}
          <div className="pt-1 flex justify-end">
            <button
              type="button"
              onClick={toggleDetail}
              className="text-2xs text-slate-400 hover:text-blue-500 transition-colors flex items-center gap-1 min-h-7 min-w-7 px-2 py-1 rounded focus:outline-none focus:ring-2 focus:ring-primary/50"
              title={
                showDetail
                  ? t('agent.subagent.hideDetails', 'Hide details')
                  : t('agent.subagent.viewDetails', 'Show details')
              }
            >
              <Info size={12} />
              <span>
                {showDetail
                  ? t('agent.subagent.hideDetails', 'Hide details')
                  : t('agent.subagent.viewDetails', 'Show details')}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Inline detail panel (2.2 preview — rendered inside card) */}
      {showDetail && (
        <SubAgentDetailPanel
          group={group}
          onClose={() => {
            setShowDetail(false);
          }}
        />
      )}
    </div>
  );
});

SubAgentTimeline.displayName = 'SubAgentTimeline';
