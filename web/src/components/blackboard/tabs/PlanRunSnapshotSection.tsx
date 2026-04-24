import { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  AlertTriangle,
  ClipboardCheck,
  Database,
  GitBranch,
  Loader2,
  ScrollText,
  RefreshCw,
} from 'lucide-react';

import { workspacePlanService } from '@/services/workspaceService';

import { EmptyState } from '../EmptyState';
import { StatBadge } from '../StatBadge';

import type {
  WorkspacePlanNode,
  WorkspacePlanEvent,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
  WorkspacePlanTaskIntent,
} from '@/types/workspace';

interface PlanRunSnapshotSectionProps {
  workspaceId: string;
}

const INTENT_TONE: Record<WorkspacePlanTaskIntent, string> = {
  todo: 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
  in_progress:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  blocked:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  done: 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
};

const OUTBOX_TONE: Record<string, string> = {
  pending:
    'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  processing:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  completed:
    'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  failed:
    'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  dead: 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
};

function statusTone(status: string): string {
  return (
    OUTBOX_TONE[status] ??
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
  );
}

function intentTone(intent: WorkspacePlanTaskIntent): string {
  return INTENT_TONE[intent];
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 6)}...${id.slice(-4)}` : id;
}

function PlanNodeRow({ node }: { node: WorkspacePlanNode }) {
  return (
    <li className="grid gap-3 border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
            {node.kind}
          </span>
          <span className="truncate text-sm font-medium text-text-primary dark:text-text-inverse">
            {node.title}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2 font-mono text-[11px] text-text-muted">
          <span>{shortId(node.id)}</span>
          {node.assignee_agent_id && <span>{shortId(node.assignee_agent_id)}</span>}
          {node.depends_on.length > 0 && <span>deps {String(node.depends_on.length)}</span>}
        </div>
      </div>
      <span
        className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${intentTone(
          node.intent
        )}`}
      >
        {node.intent}
      </span>
      <span className="inline-flex h-7 items-center rounded-full border border-border-light bg-surface-light px-2.5 text-[11px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
        {node.execution}
      </span>
    </li>
  );
}

function OutboxRow({ item }: { item: WorkspacePlanOutboxItem }) {
  return (
    <li className="grid gap-2 border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-text-primary dark:text-text-inverse">
            {item.event_type}
          </span>
          <span className="font-mono text-[11px] text-text-muted">{shortId(item.id)}</span>
        </div>
        <div className="mt-1 text-[11px] text-text-secondary dark:text-text-muted">
          {String(item.attempt_count)} / {String(item.max_attempts)}
          {item.last_error ? ` · ${item.last_error}` : ''}
        </div>
      </div>
      <span
        className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${statusTone(
          item.status
        )}`}
      >
        {item.status}
      </span>
    </li>
  );
}

function EventRow({ event }: { event: WorkspacePlanEvent }) {
  const summary = typeof event.payload.summary === 'string' ? event.payload.summary : '';
  return (
    <li className="border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="truncate text-sm font-medium text-text-primary dark:text-text-inverse">
          {event.event_type}
        </span>
        {event.node_id && (
          <span className="font-mono text-[11px] text-text-muted">{shortId(event.node_id)}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-text-secondary dark:text-text-muted">
        <span>{event.source}</span>
        {event.attempt_id && <span>{shortId(event.attempt_id)}</span>}
      </div>
      {summary && (
        <div className="mt-1 line-clamp-2 text-xs text-text-secondary dark:text-text-muted">
          {summary}
        </div>
      )}
    </li>
  );
}

export function PlanRunSnapshotSection({ workspaceId }: PlanRunSnapshotSectionProps) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSnapshot = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextSnapshot = await workspacePlanService.getSnapshot(workspaceId, {
        outboxLimit: 8,
        eventLimit: 8,
      });
      setSnapshot(nextSnapshot);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    setIsLoading(true);
    setError(null);
    workspacePlanService
      .getSnapshot(workspaceId, { outboxLimit: 8, eventLimit: 8 })
      .then((nextSnapshot) => {
        if (isMounted) {
          setSnapshot(nextSnapshot);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });
    return () => {
      isMounted = false;
    };
  }, [workspaceId]);

  const runnableNodes = useMemo(() => {
    return (
      snapshot?.plan?.nodes.filter((node) => node.kind === 'task' || node.kind === 'verify') ?? []
    );
  }, [snapshot]);

  const visibleNodes = runnableNodes.slice(0, 8);
  const plan = snapshot?.plan ?? null;
  const outbox = snapshot?.outbox ?? [];
  const blackboard = snapshot?.blackboard ?? [];
  const events = snapshot?.events ?? [];

  return (
    <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-text-secondary dark:text-text-muted" aria-hidden />
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.planRunTitle', 'Plan run')}
            </h3>
          </div>
          <p className="mt-1 text-xs text-text-secondary dark:text-text-muted">
            {t('blackboard.planRunDescription', 'Durable plan, blackboard, and supervisor queue')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadSnapshot()}
          disabled={isLoading}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-xs font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt"
          aria-label={t('blackboard.planRunRefresh', 'Refresh plan run')}
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          )}
          <span>{t('blackboard.planRunRefreshShort', 'Refresh')}</span>
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-error-border bg-error-bg p-3 text-xs text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}

      {!error && !isLoading && !plan && (
        <div className="mt-4">
          <EmptyState>
            {t('blackboard.planRunEmpty', 'No durable plan has been started for this workspace.')}
          </EmptyState>
        </div>
      )}

      {plan && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            <StatBadge label={t('blackboard.planRunStatus', 'Plan status')} value={plan.status} />
            <StatBadge
              label={t('blackboard.planRunNodes', 'Runnable nodes')}
              value={String(runnableNodes.length)}
            />
            <StatBadge
              label={t('blackboard.planRunCompleted', 'Done')}
              value={String(plan.counts['intent:done'] ?? 0)}
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

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.9fr)]">
            <div className="rounded-lg border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-background-dark/35">
              <div className="flex items-center gap-2 border-b border-border-separator py-3 dark:border-border-dark">
                <ClipboardCheck
                  className="h-4 w-4 text-text-secondary dark:text-text-muted"
                  aria-hidden
                />
                <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                  {t('blackboard.planRunNodesTitle', 'Execution DAG')}
                </div>
              </div>
              <ul>
                {visibleNodes.map((node) => (
                  <PlanNodeRow key={node.id} node={node} />
                ))}
              </ul>
              {visibleNodes.length === 0 && (
                <div className="py-4">
                  <EmptyState>
                    {t('blackboard.planRunNoNodes', 'No runnable plan nodes are available.')}
                  </EmptyState>
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="rounded-lg border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-background-dark/35">
                <div className="flex items-center gap-2 border-b border-border-separator py-3 dark:border-border-dark">
                  <Database
                    className="h-4 w-4 text-text-secondary dark:text-text-muted"
                    aria-hidden
                  />
                  <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                    {t('blackboard.planRunBlackboardTitle', 'Typed blackboard')}
                  </div>
                </div>
                <div className="space-y-2 py-3">
                  {blackboard.slice(0, 4).map((entry) => (
                    <div
                      key={`${entry.key}:${String(entry.version)}`}
                      className="flex items-center justify-between gap-3 text-xs"
                    >
                      <span className="min-w-0 truncate font-medium text-text-primary dark:text-text-inverse">
                        {entry.key}
                      </span>
                      <span className="shrink-0 rounded-full border border-border-light bg-surface-light px-2 py-0.5 font-mono text-[10px] text-text-muted dark:border-border-dark dark:bg-surface-dark">
                        v{String(entry.version)}
                      </span>
                    </div>
                  ))}
                  {blackboard.length === 0 && (
                    <EmptyState>
                      {t('blackboard.planRunNoBlackboard', 'No typed entries yet.')}
                    </EmptyState>
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-background-dark/35">
                <div className="flex items-center gap-2 border-b border-border-separator py-3 dark:border-border-dark">
                  <ScrollText
                    className="h-4 w-4 text-text-secondary dark:text-text-muted"
                    aria-hidden
                  />
                  <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                    {t('blackboard.planRunEventsTitle', 'Events')}
                  </div>
                </div>
                <ul>
                  {events.slice(0, 4).map((event) => (
                    <EventRow key={event.id} event={event} />
                  ))}
                </ul>
                {events.length === 0 && (
                  <div className="py-3">
                    <EmptyState>{t('blackboard.planRunNoEvents', 'No plan events.')}</EmptyState>
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-background-dark/35">
                <div className="flex items-center gap-2 border-b border-border-separator py-3 dark:border-border-dark">
                  <RefreshCw
                    className="h-4 w-4 text-text-secondary dark:text-text-muted"
                    aria-hidden
                  />
                  <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                    {t('blackboard.planRunOutboxTitle', 'Outbox')}
                  </div>
                </div>
                <ul>
                  {outbox.slice(0, 4).map((item) => (
                    <OutboxRow key={item.id} item={item} />
                  ))}
                </ul>
                {outbox.length === 0 && (
                  <div className="py-3">
                    <EmptyState>{t('blackboard.planRunNoOutbox', 'No queued events.')}</EmptyState>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
