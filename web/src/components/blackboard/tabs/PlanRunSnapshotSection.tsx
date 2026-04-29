import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock3,
  Filter,
  GitBranch,
  Loader2,
  PackageCheck,
  Pause,
  Play,
  RefreshCw,
  Repeat2,
  RotateCcw,
  Search,
  ShieldCheck,
  SkipForward,
  Split,
  Zap,
} from 'lucide-react';

import { workspaceAutonomyService, workspacePlanService } from '@/services/workspaceService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

import { EmptyState } from '../EmptyState';
import { StatBadge } from '../StatBadge';

import {
  actionEnabled,
  asRecord,
  asText,
  countDone,
  criterionSummary,
  eventLabel,
  eventSummary,
  fallbackTone,
  FILTERS,
  formatRelative,
  formatTime,
  matchesFilter,
  nodeWriteSet,
  outboxNodeId,
  planStage,
  rootGoalNeedsClosure,
  shortId,
} from './planRunSnapshotModel';
import {
  BlackboardEntryRow,
  NodeRow,
  NodeStatusIcon,
  OutboxRow,
  TimelineRow,
} from './PlanRunSnapshotParts';

import type {
  WorkspacePlanActionCapability,
  WorkspacePlanIterationSummary,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
  WorkspaceTask,
} from '@/types/workspace';

import type { NodeActionId, NodeFilter } from './planRunSnapshotModel';

interface PlanRunSnapshotSectionProps {
  workspaceId: string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
  tasks?: WorkspaceTask[] | undefined;
  refreshToken?: number | undefined;
}

const OPERATOR_REASON_LIMIT = 500;
const DEFAULT_NODE_ACTION_REASON = 'operator action from central blackboard';
const DEFAULT_RETRY_ACTION_REASON = 'operator retry from central blackboard';

function actionLabel(action: WorkspacePlanActionCapability | undefined, fallback: string): string {
  return action?.label || fallback;
}

function actionDisabledReason(
  action: WorkspacePlanActionCapability | undefined,
  fallback: string
): string {
  return action?.reason || fallback;
}

function reasonOrFallback(value: string, fallback: string): string {
  return value.trim() || fallback;
}

function nodePhaseLabel(nodeMetadata: Record<string, unknown>): string {
  const phase = nodeMetadata.iteration_phase;
  return typeof phase === 'string' && phase ? phase : 'plan';
}

function IterationLoopPanel({
  iteration,
  isActionPending,
  onAction,
}: {
  iteration: WorkspacePlanIterationSummary | null | undefined;
  isActionPending: boolean;
  onAction: (actionId: 'pause_auto_loop' | 'resume_auto_loop' | 'trigger_next_iteration') => void;
}) {
  if (!iteration) {
    return null;
  }
  const pauseAction = iteration.actions.pause_auto_loop;
  const resumeAction = iteration.actions.resume_auto_loop;
  const triggerAction = iteration.actions.trigger_next_iteration;
  const statusTone =
    iteration.loop_status === 'completed'
      ? 'text-status-text-success'
      : iteration.loop_status === 'paused' || iteration.loop_status === 'suspended'
        ? 'text-status-text-warning'
        : 'text-status-text-info';

  return (
    <div className="border-t border-border-separator px-4 py-4 dark:border-border-dark">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
            <Repeat2 className="h-4 w-4" aria-hidden />
            Iteration {iteration.current_iteration}
          </div>
          <div className="mt-2 text-sm font-medium text-text-primary dark:text-text-inverse">
            {iteration.active_phase_label}
          </div>
          <div className={`mt-1 text-xs font-medium uppercase ${statusTone}`}>
            {iteration.loop_status}
          </div>
          {iteration.current_sprint_goal && (
            <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
              {iteration.current_sprint_goal}
            </p>
          )}
          <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
            {iteration.next_action}
          </p>
          {iteration.review_summary && (
            <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
              {iteration.review_summary}
            </p>
          )}
          {iteration.stop_reason && (
            <p className="mt-1 break-words text-xs leading-5 text-status-text-warning dark:text-status-text-warning-dark">
              {iteration.stop_reason}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-start gap-2">
          <StatBadge
            label="Sprint tasks"
            value={`${String(iteration.task_count)}/${String(iteration.task_budget)}`}
          />
          <StatBadge label="Loop" value={iteration.loop_label} />
          <StatBadge
            label="Completed"
            value={`${String(iteration.completed_iterations.length)}/${String(iteration.max_iterations)}`}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(pauseAction)}
          title={actionDisabledReason(pauseAction, 'Pause is not available.')}
          onClick={() => {
            onAction('pause_auto_loop');
          }}
        >
          <Pause className="h-3.5 w-3.5" aria-hidden />
          Pause
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(resumeAction)}
          title={actionDisabledReason(resumeAction, 'Resume is not available.')}
          onClick={() => {
            onAction('resume_auto_loop');
          }}
        >
          <Play className="h-3.5 w-3.5" aria-hidden />
          Resume
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(triggerAction)}
          title={actionDisabledReason(triggerAction, 'Next iteration is not available.')}
          onClick={() => {
            onAction('trigger_next_iteration');
          }}
        >
          <SkipForward className="h-3.5 w-3.5" aria-hidden />
          Plan next
        </button>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {iteration.phases.map((phase) => {
          const isActive = phase.id === iteration.active_phase;
          return (
            <div
              key={phase.id}
              className={`min-w-0 rounded-md border px-3 py-2 ${
                isActive
                  ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                  : 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-semibold">{phase.label}</span>
                <span className="font-mono text-[11px]">{phase.progress}%</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-background-light/70 dark:bg-background-dark/60">
                <div
                  className={`h-full rounded-full ${
                    phase.blocked > 0
                      ? 'bg-status-text-error'
                      : isActive
                        ? 'bg-status-text-info'
                        : 'bg-text-muted'
                  }`}
                  style={{ width: `${String(Math.max(0, Math.min(phase.progress, 100)))}%` }}
                />
              </div>
              <div className="mt-1.5 text-[11px]">
                {phase.done}/{phase.total || 0}
                {phase.running > 0 ? ` · ${String(phase.running)} active` : ''}
                {phase.blocked > 0 ? ` · ${String(phase.blocked)} blocked` : ''}
              </div>
            </div>
          );
        })}
      </div>

      {(iteration.deliverables.length > 0 || iteration.feedback_items.length > 0) && (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {iteration.deliverables.length > 0 && (
            <div className="min-w-0 rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                <PackageCheck className="h-4 w-4" aria-hidden />
                Outputs
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {iteration.deliverables.map((item) => (
                  <span
                    key={item}
                    className="max-w-full truncate rounded border border-border-light bg-surface-muted px-2 py-1 font-mono text-[11px] text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>
          )}
          {iteration.feedback_items.length > 0 && (
            <div className="min-w-0 rounded-md border border-warning-border bg-warning-bg p-3 text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase">
                <AlertTriangle className="h-4 w-4" aria-hidden />
                Feedback
              </div>
              <ul className="mt-2 space-y-1 text-xs leading-5">
                {iteration.feedback_items.map((item) => (
                  <li key={item} className="break-words">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {iteration.history.length > 0 && (
        <div className="mt-4 border-t border-border-separator pt-3 dark:border-border-dark">
          <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
            Review history
          </div>
          <div className="mt-2 space-y-2">
            {iteration.history.slice(-3).map((item) => (
              <div
                key={`${String(item.iteration_index)}-${item.verdict}-${item.summary}`}
                className="min-w-0 rounded-md border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-text-primary dark:text-text-inverse">
                    Iteration {item.iteration_index}
                  </span>
                  <span className="uppercase">{item.verdict}</span>
                  <span>{Math.round(item.confidence * 100)}%</span>
                </div>
                <p className="mt-1 break-words leading-5">{item.summary}</p>
                {item.next_sprint_goal && (
                  <p className="mt-1 break-words leading-5">{item.next_sprint_goal}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function PlanRunSnapshotSection({
  workspaceId,
  tenantId,
  projectId,
  tasks,
  refreshToken,
}: PlanRunSnapshotSectionProps) {
  const { t } = useTranslation();
  const taskList = useMemo(() => tasks ?? [], [tasks]);
  const isMountedRef = useRef(true);
  const lastRefreshTokenRef = useRef(refreshToken ?? 0);
  const [snapshot, setSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [filter, setFilter] = useState<NodeFilter>('all');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isActionPending, setIsActionPending] = useState(false);
  const [isTickPending, setIsTickPending] = useState(false);
  const [operatorReason, setOperatorReason] = useState('');
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  const loadSnapshot = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setIsLoading(true);
      }
      setError(null);
      try {
        const nextSnapshot = await workspacePlanService.getSnapshot(workspaceId, {
          outboxLimit: 20,
          eventLimit: 80,
        });
        if (!isMountedRef.current) {
          return;
        }
        setSnapshot(nextSnapshot);
        setLastUpdatedAt(new Date());
      } catch (err) {
        if (isMountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (isMountedRef.current) {
          setIsLoading(false);
        }
      }
    },
    [workspaceId]
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;

    const schedule = () => {
      const visible = document.visibilityState === 'visible';
      const interval = visible ? 8000 : 30000;
      timer = window.setTimeout(() => {
        if (cancelled) {
          return;
        }
        void loadSnapshot({ silent: true }).then(() => {
          if (!cancelled) {
            schedule();
          }
        });
      }, interval);
    };

    void loadSnapshot();
    schedule();

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [loadSnapshot]);

  useEffect(() => {
    const nextRefreshToken = refreshToken ?? 0;
    if (lastRefreshTokenRef.current === nextRefreshToken) {
      return;
    }
    lastRefreshTokenRef.current = nextRefreshToken;
    void loadSnapshot({ silent: true });
  }, [loadSnapshot, refreshToken]);

  const nodes = useMemo(() => snapshot?.plan?.nodes ?? [], [snapshot]);
  const runnableNodes = useMemo(
    () => nodes.filter((node) => node.kind === 'task' || node.kind === 'verify'),
    [nodes]
  );
  const normalizedQuery = query.trim().toLowerCase();
  const filteredNodes = useMemo(
    () =>
      runnableNodes
        .filter((node) => matchesFilter(node, filter))
        .filter((node) => {
          if (!normalizedQuery) {
            return true;
          }
          return [
            node.id,
            node.title,
            node.description,
            node.intent,
            node.execution,
            node.assignee_agent_id ?? '',
            node.current_attempt_id ?? '',
          ]
            .join(' ')
            .toLowerCase()
            .includes(normalizedQuery);
        }),
    [filter, normalizedQuery, runnableNodes]
  );
  const selectedNode = useMemo(() => {
    return nodes.find((node) => node.id === selectedNodeId) ?? filteredNodes[0] ?? nodes[0] ?? null;
  }, [filteredNodes, nodes, selectedNodeId]);

  useEffect(() => {
    if (selectedNode && selectedNode.id !== selectedNodeId) {
      setSelectedNodeId(selectedNode.id);
    }
  }, [selectedNode, selectedNodeId]);

  const plan = snapshot?.plan ?? null;
  const outbox = useMemo(() => snapshot?.outbox ?? [], [snapshot]);
  const events = useMemo(() => snapshot?.events ?? [], [snapshot]);
  const blackboard = useMemo(() => snapshot?.blackboard ?? [], [snapshot]);
  const rootGoal = snapshot?.root_goal ?? null;
  const iteration = snapshot?.iteration ?? null;
  const stage = planStage(snapshot);
  const doneCount = countDone(runnableNodes);
  const rootUnitCount = rootGoal ? 1 : 0;
  const totalCompletionUnits = runnableNodes.length + rootUnitCount;
  const completedUnits = doneCount + (rootGoal?.status === 'done' ? 1 : 0);
  const completion =
    totalCompletionUnits > 0 ? Math.round((completedUnits / totalCompletionUnits) * 100) : 0;
  const latestEvent = events[0] ?? null;
  const isStale = lastUpdatedAt ? Date.now() - lastUpdatedAt.getTime() > 20000 : false;

  const selectedEvents = useMemo(() => {
    if (!selectedNode) {
      return events.slice(0, 12);
    }
    const related = events.filter(
      (event) =>
        event.node_id === selectedNode.id ||
        event.attempt_id === selectedNode.current_attempt_id ||
        asText(asRecord(event.payload).node_id) === selectedNode.id
    );
    return (related.length > 0 ? related : events)
      .filter((event) => {
        if (!normalizedQuery) {
          return true;
        }
        return [
          event.event_type,
          event.source,
          event.node_id ?? '',
          event.attempt_id ?? '',
          event.actor_id ?? '',
          eventSummary(event),
        ]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 12);
  }, [events, normalizedQuery, selectedNode]);

  const selectedOutbox = useMemo(() => {
    if (!selectedNode) {
      return outbox.slice(0, 8);
    }
    const related = outbox.filter((item) => outboxNodeId(item) === selectedNode.id);
    return (related.length > 0 ? related : outbox)
      .filter((item) => {
        if (!normalizedQuery) {
          return true;
        }
        return [
          item.id,
          item.event_type,
          item.status,
          item.last_error ?? '',
          outboxNodeId(item),
          asText(item.payload),
        ]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 8);
  }, [normalizedQuery, outbox, selectedNode]);

  const visibleBlackboard = useMemo(() => {
    return blackboard
      .filter((entry) => {
        if (!normalizedQuery) {
          return true;
        }
        return [entry.key, entry.published_by, asText(entry.value)]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 8);
  }, [blackboard, normalizedQuery]);

  const linkedTask = useMemo(() => {
    if (!selectedNode) {
      return null;
    }
    return (
      taskList.find(
        (task) =>
          task.id === selectedNode.workspace_task_id ||
          task.current_attempt_id === selectedNode.current_attempt_id
      ) ?? null
    );
  }, [selectedNode, taskList]);

  const attemptHref =
    tenantId && projectId && linkedTask?.current_attempt_conversation_id
      ? buildAgentWorkspacePath({
          tenantId,
          projectId,
          workspaceId,
          conversationId: linkedTask.current_attempt_conversation_id,
        })
      : '';
  const selectedWriteSet = selectedNode ? nodeWriteSet(selectedNode) : [];
  const openAttemptAction = selectedNode?.actions?.open_attempt;
  const requestReplanAction = selectedNode?.actions?.request_replan;
  const reopenBlockedAction = selectedNode?.actions?.reopen_blocked;
  const canOpenAttempt =
    Boolean(attemptHref) && (!openAttemptAction || actionEnabled(openAttemptAction));
  const showOpenAttemptAction = Boolean(openAttemptAction || attemptHref);
  const openAttemptDisabledReason = !actionEnabled(openAttemptAction)
    ? actionDisabledReason(openAttemptAction, 'No worker attempt has been linked yet.')
    : 'Attempt conversation is not available in this workspace projection.';
  const requestReplanDisabledReason = !actionEnabled(requestReplanAction)
    ? actionDisabledReason(requestReplanAction, 'This node cannot be replanned.')
    : undefined;
  const reopenBlockedDisabledReason = !actionEnabled(reopenBlockedAction)
    ? actionDisabledReason(reopenBlockedAction, 'This node cannot be reopened.')
    : undefined;

  const formatAutonomyTickMessage = (result: { triggered: boolean; reason: string }) => {
    if (result.triggered) {
      return t('blackboard.planRunAutonomyTriggered', 'Leader scheduled the next autonomy step.');
    }
    if (result.reason === 'cooling_down') {
      return t(
        'blackboard.planRunAutonomyCoolingDown',
        'Autonomy is cooling down. Use Force run to bypass the cooldown.'
      );
    }
    if (result.reason === 'no_open_root') {
      return t('blackboard.planRunAutonomyNoRoot', 'No open root goal needs progress.');
    }
    if (result.reason === 'no_root_needs_progress') {
      return t('blackboard.planRunAutonomyStable', 'All root goals are currently stable.');
    }
    return t(
      'blackboard.planRunAutonomyNoop',
      `Autonomy did not run: ${result.reason || 'unknown'}`
    );
  };

  const runAutonomyTick = async (force: boolean) => {
    setIsTickPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await workspaceAutonomyService.tick(workspaceId, { force });
      setActionMessage(formatAutonomyTickMessage(result));
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTickPending(false);
    }
  };

  const runNodeAction = async (actionId: NodeActionId) => {
    if (!selectedNode) {
      return;
    }
    const action = selectedNode.actions?.[actionId];
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This action is not available for the selected node.');
      return;
    }
    if (
      action?.requires_confirmation &&
      !window.confirm(
        t(
          'blackboard.planRunConfirmNodeAction',
          `Run "${actionLabel(action, actionId)}" for this durable plan node?`
        )
      )
    ) {
      return;
    }

    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result =
        actionId === 'reopen_blocked'
          ? await workspacePlanService.reopenBlockedNode(workspaceId, selectedNode.id, {
              reason,
            })
          : await workspacePlanService.requestNodeReplan(workspaceId, selectedNode.id, {
              reason,
            });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const retryOutbox = async (item: WorkspacePlanOutboxItem) => {
    const action = item.actions?.retry_outbox;
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This queue job cannot be retried.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_RETRY_ACTION_REASON);
      const result = await workspacePlanService.retryOutboxItem(workspaceId, item.id, {
        reason,
      });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const runIterationAction = async (
    actionId: 'pause_auto_loop' | 'resume_auto_loop' | 'trigger_next_iteration'
  ) => {
    const action = iteration?.actions[actionId];
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This iteration action is not available.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result =
        actionId === 'pause_auto_loop'
          ? await workspacePlanService.pauseAutoLoop(workspaceId, { reason })
          : actionId === 'resume_auto_loop'
            ? await workspacePlanService.resumeAutoLoop(workspaceId, { reason })
            : await workspacePlanService.triggerNextIteration(workspaceId, { reason });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  return (
    <section className="rounded-lg border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <GitBranch className="h-4 w-4 shrink-0 text-text-secondary dark:text-text-muted" />
            <h3 className="text-lg font-semibold leading-6 text-text-primary dark:text-text-inverse">
              {t('blackboard.planRunTitle', 'Plan run')}
            </h3>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-text-secondary dark:text-text-muted">
            <span>{stage}</span>
            <span>Updated {formatRelative(lastUpdatedAt)}</span>
            {latestEvent && <span>{eventLabel(latestEvent)}</span>}
            {isStale && <span className="text-status-text-warning">stale snapshot</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
          <button
            type="button"
            onClick={() => void runAutonomyTick(false)}
            disabled={isTickPending}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-info-border bg-info-bg px-3 text-sm font-medium text-status-text-info transition-colors hover:bg-info-bg/80 disabled:cursor-not-allowed disabled:opacity-60 dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark lg:min-h-9 lg:text-xs"
          >
            {isTickPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Zap className="h-4 w-4" aria-hidden />
            )}
            {t('blackboard.planRunRunAutonomy', 'Run')}
          </button>
          <button
            type="button"
            onClick={() => void runAutonomyTick(true)}
            disabled={isTickPending}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
          >
            <Zap className="h-4 w-4" aria-hidden />
            {t('blackboard.planRunForceAutonomy', 'Force')}
          </button>
          <button
            type="button"
            onClick={() => {
              void loadSnapshot();
            }}
            disabled={isLoading}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden />
            )}
            {t('blackboard.planRunRefreshShort', 'Refresh')}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-4 flex items-start gap-2 rounded-md border border-error-border bg-error-bg p-3 text-xs text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="break-words">{error}</span>
        </div>
      )}

      {(actionError || actionMessage) && (
        <div
          className={`mx-4 mb-4 rounded-md border p-3 text-xs ${
            actionError
              ? 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark'
              : 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
          }`}
          aria-live="polite"
        >
          {actionError ?? actionMessage}
        </div>
      )}

      {!error && !isLoading && !plan && (
        <div className="border-t border-border-separator px-4 py-6 dark:border-border-dark">
          <EmptyState>
            {t('blackboard.planRunEmpty', 'No durable plan has been started for this workspace.')}
          </EmptyState>
        </div>
      )}

      {plan && (
        <div className="border-t border-border-separator dark:border-border-dark">
          <div className="flex flex-wrap gap-2 px-4 py-3">
            <StatBadge label={t('blackboard.planRunStatus', 'Plan status')} value={plan.status} />
            <StatBadge label={t('blackboard.planRunStage', 'Stage')} value={stage} />
            <StatBadge
              label={t('blackboard.planRunCompleted', 'Done')}
              value={`${String(completedUnits)} / ${String(totalCompletionUnits)}`}
            />
            <StatBadge
              label={t('blackboard.planRunCompletion', 'Completion')}
              value={`${String(completion)}%`}
            />
            {rootGoal && (
              <StatBadge
                label={t('blackboard.planRunRootStatus', 'Root')}
                value={rootGoal.status}
              />
            )}
            {rootGoal?.evidence_grade && (
              <StatBadge
                label={t('blackboard.planRunEvidenceGrade', 'Evidence')}
                value={rootGoal.evidence_grade}
              />
            )}
            <StatBadge
              label={t('blackboard.planRunQueue', 'Queue')}
              value={String(outbox.length)}
            />
            <StatBadge
              label={t('blackboard.planRunEvents', 'Events')}
              value={String(events.length)}
            />
          </div>
          {rootGoalNeedsClosure(snapshot) && rootGoal?.completion_blocker_reason && (
            <div className="border-t border-warning-border bg-warning-bg px-4 py-3 text-sm text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
              {rootGoal.completion_blocker_reason}
            </div>
          )}
          <IterationLoopPanel
            iteration={iteration}
            isActionPending={isActionPending}
            onAction={(actionId) => void runIterationAction(actionId)}
          />

          <div className="grid min-h-[520px] xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.78fr)]">
            <div className="min-w-0 border-t border-border-separator dark:border-border-dark xl:border-t-0">
              <div className="flex flex-col gap-3 border-b border-border-separator px-4 py-3 dark:border-border-dark 2xl:flex-row 2xl:items-center 2xl:justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                  <Split className="h-4 w-4" aria-hidden />
                  {t('blackboard.planRunNodesTitle', 'Execution DAG')}
                </div>
                <label className="relative min-w-0 flex-1 2xl:max-w-64">
                  <span className="sr-only">
                    {t('blackboard.planRunSearch', 'Search plan run')}
                  </span>
                  <Search
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
                    aria-hidden
                  />
                  <input
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                    }}
                    placeholder={t('blackboard.planRunSearchPlaceholder', 'Search run')}
                    className="h-11 w-full rounded-md border border-border-light bg-surface-light pl-9 pr-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-info-border focus:ring-2 focus:ring-ring dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:h-9 lg:text-xs"
                  />
                </label>
                <div className="flex flex-wrap gap-2" aria-label="Filter plan nodes">
                  {FILTERS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setFilter(item.id);
                      }}
                      className={`inline-flex min-h-11 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors lg:min-h-9 ${
                        filter === item.id
                          ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                          : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                      }`}
                    >
                      <Filter className="h-3.5 w-3.5" aria-hidden />
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              {filteredNodes.length > 0 ? (
                <div className="divide-y-0">
                  {filteredNodes.map((node) => (
                    <NodeRow
                      key={node.id}
                      node={node}
                      isSelected={selectedNode?.id === node.id}
                      onSelect={() => {
                        setSelectedNodeId(node.id);
                      }}
                    />
                  ))}
                </div>
              ) : (
                <div className="px-4 py-6">
                  <EmptyState>
                    {t('blackboard.planRunNoNodes', 'No runnable plan nodes match this view.')}
                  </EmptyState>
                </div>
              )}
            </div>

            <aside className="min-w-0 border-t border-border-separator dark:border-border-dark xl:border-l xl:border-t-0">
              {selectedNode ? (
                <div className="flex min-h-full flex-col">
                  <div className="border-b border-border-separator px-4 py-4 dark:border-border-dark">
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${fallbackTone(
                              selectedNode.intent
                            )}`}
                          >
                            {selectedNode.intent}
                          </span>
                          <span className="rounded-full border border-border-light px-2.5 py-1 text-[11px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
                            {selectedNode.execution}
                          </span>
                        </div>
                        <h4 className="mt-3 break-words text-base font-semibold leading-6 text-text-primary dark:text-text-inverse">
                          {selectedNode.title}
                        </h4>
                        {selectedNode.description && (
                          <p className="mt-2 line-clamp-4 break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
                            {selectedNode.description}
                          </p>
                        )}
                      </div>
                      <NodeStatusIcon node={selectedNode} />
                    </div>

                    <div className="mt-4 grid gap-2 text-xs text-text-secondary dark:text-text-muted sm:grid-cols-2">
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Node
                        </span>{' '}
                        <span className="font-mono">{shortId(selectedNode.id)}</span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Owner
                        </span>{' '}
                        <span className="font-mono">{shortId(selectedNode.assignee_agent_id)}</span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Attempt
                        </span>{' '}
                        <span className="font-mono">
                          {shortId(selectedNode.current_attempt_id)}
                        </span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Updated
                        </span>{' '}
                        {formatTime(selectedNode.updated_at ?? selectedNode.created_at)}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Phase
                        </span>{' '}
                        {nodePhaseLabel(asRecord(selectedNode.metadata))}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Checks
                        </span>{' '}
                        {criterionSummary(selectedNode)}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Write set
                        </span>{' '}
                        {selectedWriteSet.length > 0
                          ? `${String(selectedWriteSet.length)} file(s)`
                          : 'none'}
                      </div>
                    </div>

                    {selectedWriteSet.length > 0 && (
                      <div className="mt-3 rounded-md border border-border-light bg-surface-muted/70 p-3 dark:border-border-dark dark:bg-background-dark/35">
                        <div className="text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
                          Write-scope guard
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {selectedWriteSet.slice(0, 8).map((path) => (
                            <span
                              key={path}
                              className="rounded border border-border-light bg-surface-light px-1.5 py-0.5 font-mono text-[10px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted"
                            >
                              {path}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <label className="mt-4 block">
                      <span className="text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
                        {t('blackboard.planRunOperatorReason', 'Operator reason')}
                      </span>
                      <textarea
                        value={operatorReason}
                        onChange={(event) => {
                          setOperatorReason(event.target.value.slice(0, OPERATOR_REASON_LIMIT));
                        }}
                        maxLength={OPERATOR_REASON_LIMIT}
                        rows={2}
                        placeholder={t(
                          'blackboard.planRunOperatorReasonPlaceholder',
                          'Optional reason for replan, reopen, or retry'
                        )}
                        className="mt-2 w-full resize-y rounded-md border border-border-light bg-surface-light px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-info-border focus:ring-2 focus:ring-ring dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:text-xs"
                      />
                    </label>

                    <div className="mt-4 flex flex-wrap gap-2">
                      {showOpenAttemptAction &&
                        (canOpenAttempt ? (
                          <Link
                            to={attemptHref}
                            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                          >
                            <ArrowUpRight className="h-4 w-4" aria-hidden />
                            {actionLabel(
                              openAttemptAction,
                              t('blackboard.planRunOpenAttempt', 'Open attempt')
                            )}
                          </Link>
                        ) : (
                          <button
                            type="button"
                            disabled
                            title={openAttemptDisabledReason}
                            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary opacity-60 disabled:cursor-not-allowed dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:min-h-9 lg:text-xs"
                          >
                            <ArrowUpRight className="h-4 w-4" aria-hidden />
                            {actionLabel(
                              openAttemptAction,
                              t('blackboard.planRunOpenAttempt', 'Open attempt')
                            )}
                          </button>
                        ))}
                      <button
                        type="button"
                        onClick={() => void runNodeAction('request_replan')}
                        disabled={isActionPending || !actionEnabled(requestReplanAction)}
                        title={requestReplanDisabledReason}
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden />
                        {actionLabel(
                          requestReplanAction,
                          t('blackboard.planRunRequestReplan', 'Request replan')
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => void runNodeAction('reopen_blocked')}
                        disabled={isActionPending || !actionEnabled(reopenBlockedAction)}
                        title={reopenBlockedDisabledReason}
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden />
                        {actionLabel(
                          reopenBlockedAction,
                          t('blackboard.planRunReopenNode', 'Reopen')
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="grid flex-1 grid-rows-[auto_auto_auto]">
                    <section className="min-w-0 border-b border-border-separator px-4 py-3 dark:border-border-dark">
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                        <Clock3 className="h-4 w-4" aria-hidden />
                        {t('blackboard.planRunNarrativeTitle', 'Execution narrative')}
                      </div>
                      <ul className="mt-1">
                        {selectedEvents.map((event) => (
                          <TimelineRow key={event.id} event={event} />
                        ))}
                      </ul>
                      {selectedEvents.length === 0 && (
                        <div className="py-3">
                          <EmptyState>
                            {t('blackboard.planRunNoEvents', 'No plan events.')}
                          </EmptyState>
                        </div>
                      )}
                    </section>

                    <section className="min-w-0 border-b border-border-separator px-4 py-3 dark:border-border-dark">
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                        <Activity className="h-4 w-4" aria-hidden />
                        {t('blackboard.planRunOutboxTitle', 'Outbox')}
                      </div>
                      <ul className="mt-1">
                        {selectedOutbox.map((item) => (
                          <OutboxRow
                            key={item.id}
                            item={item}
                            onRetry={(target) => {
                              void retryOutbox(target);
                            }}
                            isActionPending={isActionPending}
                          />
                        ))}
                      </ul>
                      {selectedOutbox.length === 0 && (
                        <div className="py-3">
                          <EmptyState>
                            {t('blackboard.planRunNoOutbox', 'No queued events.')}
                          </EmptyState>
                        </div>
                      )}
                    </section>

                    <section className="min-w-0 px-4 py-3">
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                        <ShieldCheck className="h-4 w-4" aria-hidden />
                        {t('blackboard.planRunBlackboardTitle', 'Typed blackboard')}
                      </div>
                      <ul className="mt-1">
                        {visibleBlackboard.map((entry) => (
                          <BlackboardEntryRow
                            key={`${entry.key}:${String(entry.version)}`}
                            entry={entry}
                          />
                        ))}
                      </ul>
                      {visibleBlackboard.length === 0 && (
                        <div className="py-3">
                          <EmptyState>
                            {t('blackboard.planRunNoBlackboard', 'No typed entries yet.')}
                          </EmptyState>
                        </div>
                      )}
                    </section>
                  </div>
                </div>
              ) : (
                <div className="px-4 py-6">
                  <EmptyState>
                    {t('blackboard.planRunSelectNodeEmpty', 'Select a node to inspect it.')}
                  </EmptyState>
                </div>
              )}
            </aside>
          </div>
        </div>
      )}
    </section>
  );
}
