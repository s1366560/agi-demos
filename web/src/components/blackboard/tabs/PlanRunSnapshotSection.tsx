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
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Split,
} from 'lucide-react';

import { workspacePlanService } from '@/services/workspaceService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

import { EmptyState } from '../EmptyState';
import { StatBadge } from '../StatBadge';

import {
  actionEnabled,
  asRecord,
  asText,
  countDone,
  eventLabel,
  eventSummary,
  fallbackTone,
  FILTERS,
  formatRelative,
  formatTime,
  matchesFilter,
  outboxNodeId,
  planStage,
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
}

export function PlanRunSnapshotSection({
  workspaceId,
  tenantId,
  projectId,
  tasks,
}: PlanRunSnapshotSectionProps) {
  const { t } = useTranslation();
  const taskList = useMemo(() => tasks ?? [], [tasks]);
  const isMountedRef = useRef(true);
  const [snapshot, setSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [filter, setFilter] = useState<NodeFilter>('all');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isActionPending, setIsActionPending] = useState(false);
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
  const stage = planStage(snapshot);
  const doneCount = countDone(runnableNodes);
  const completion =
    runnableNodes.length > 0 ? Math.round((doneCount / runnableNodes.length) * 100) : 0;
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
      !window.confirm('Send this node back for durable supervisor recovery?')
    ) {
      return;
    }

    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result =
        actionId === 'reopen_blocked'
          ? await workspacePlanService.reopenBlockedNode(workspaceId, selectedNode.id, {
              reason: 'operator action from central blackboard',
            })
          : await workspacePlanService.requestNodeReplan(workspaceId, selectedNode.id, {
              reason: 'operator action from central blackboard',
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
      const result = await workspacePlanService.retryOutboxItem(workspaceId, item.id, {
        reason: 'operator retry from central blackboard',
      });
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

      {error && (
        <div className="mx-4 mb-4 flex items-start gap-2 rounded-md border border-error-border bg-error-bg p-3 text-xs text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="break-words">{error}</span>
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
              value={`${String(doneCount)} / ${String(runnableNodes.length)}`}
            />
            <StatBadge
              label={t('blackboard.planRunCompletion', 'Completion')}
              value={`${String(completion)}%`}
            />
            <StatBadge
              label={t('blackboard.planRunQueue', 'Queue')}
              value={String(outbox.length)}
            />
            <StatBadge
              label={t('blackboard.planRunEvents', 'Events')}
              value={String(events.length)}
            />
          </div>

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
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      {attemptHref && (
                        <Link
                          to={attemptHref}
                          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                        >
                          <ArrowUpRight className="h-4 w-4" aria-hidden />
                          {t('blackboard.planRunOpenAttempt', 'Open attempt')}
                        </Link>
                      )}
                      <button
                        type="button"
                        onClick={() => void runNodeAction('request_replan')}
                        disabled={
                          isActionPending || !actionEnabled(selectedNode.actions?.request_replan)
                        }
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden />
                        {t('blackboard.planRunRequestReplan', 'Request replan')}
                      </button>
                      <button
                        type="button"
                        onClick={() => void runNodeAction('reopen_blocked')}
                        disabled={
                          isActionPending || !actionEnabled(selectedNode.actions?.reopen_blocked)
                        }
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden />
                        {t('blackboard.planRunReopenNode', 'Reopen')}
                      </button>
                    </div>

                    {(actionError || actionMessage) && (
                      <div
                        className={`mt-3 rounded-md border p-3 text-xs ${
                          actionError
                            ? 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark'
                            : 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
                        }`}
                        aria-live="polite"
                      >
                        {actionError ?? actionMessage}
                      </div>
                    )}
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
