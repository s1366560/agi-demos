import {
  Activity,
  CheckCircle2,
  CircleDashed,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';

import {
  actionEnabled,
  asText,
  criterionSummary,
  eventLabel,
  eventSummary,
  fallbackTone,
  formatTime,
  nodeWriteSet,
  outboxNodeId,
  shortId,
} from './planRunSnapshotModel';

import type {
  WorkspacePlanBlackboardEntry,
  WorkspacePlanEvent,
  WorkspacePlanNode,
  WorkspacePlanOutboxItem,
} from '@/types/workspace';

export function NodeStatusIcon({ node }: { node: WorkspacePlanNode }) {
  if (node.intent === 'done') {
    return <CheckCircle2 className="h-4 w-4 text-status-text-success" aria-hidden />;
  }
  if (node.intent === 'blocked') {
    return <XCircle className="h-4 w-4 text-status-text-error" aria-hidden />;
  }
  if (node.execution === 'verifying' || node.execution === 'reported') {
    return <ShieldCheck className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  if (node.execution === 'running' || node.execution === 'dispatched') {
    return <Activity className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  return <CircleDashed className="h-4 w-4 text-text-muted" aria-hidden />;
}

export function NodeRow({
  node,
  isSelected,
  onSelect,
}: {
  node: WorkspacePlanNode;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const progress = Math.max(0, Math.min(100, node.progress.percent || 0));
  const writeSet = nodeWriteSet(node);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={isSelected}
      className={`w-full border-b border-border-separator px-3 py-3 text-left transition-colors last:border-b-0 hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-border-dark dark:hover:bg-surface-dark ${
        isSelected ? 'bg-surface-muted dark:bg-surface-dark' : ''
      }`}
    >
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5 shrink-0">
          <NodeStatusIcon node={node} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="rounded-full border border-border-light bg-surface-light px-2 py-0.5 text-[11px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
              {node.kind}
            </span>
            <span className="min-w-0 break-words text-sm font-semibold leading-5 text-text-primary dark:text-text-inverse">
              {node.title}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] text-text-muted">
            <span>{shortId(node.id)}</span>
            {node.assignee_agent_id && <span>owner {shortId(node.assignee_agent_id)}</span>}
            {node.depends_on.length > 0 && <span>deps {String(node.depends_on.length)}</span>}
            {node.acceptance_criteria.length > 0 && <span>checks {criterionSummary(node)}</span>}
            {writeSet.length > 0 && <span>write {String(writeSet.length)}</span>}
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-dark/10 dark:bg-surface-light/10">
            <div
              className="h-full rounded-full bg-status-text-info transition-[width] motion-reduce:transition-none"
              style={{ width: `${String(progress)}%` }}
            />
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <span
            className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${fallbackTone(
              node.intent
            )}`}
          >
            {node.intent}
          </span>
          <span className="text-[11px] uppercase text-text-muted">{node.execution}</span>
        </div>
      </div>
    </button>
  );
}

export function TimelineRow({ event }: { event: WorkspacePlanEvent }) {
  const summary = eventSummary(event);
  return (
    <li className="border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-words text-sm font-medium text-text-primary dark:text-text-inverse">
            {eventLabel(event)}
          </div>
          <div className="mt-1 flex flex-wrap gap-2 font-mono text-[11px] text-text-muted">
            <span>{formatTime(event.created_at)}</span>
            {event.node_id && <span>node {shortId(event.node_id)}</span>}
            {event.attempt_id && <span>attempt {shortId(event.attempt_id)}</span>}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-border-light px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
          {event.source}
        </span>
      </div>
      {summary && (
        <p className="mt-2 line-clamp-3 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
          {summary}
        </p>
      )}
    </li>
  );
}

export function OutboxRow({
  item,
  onRetry,
  isActionPending,
}: {
  item: WorkspacePlanOutboxItem;
  onRetry: (item: WorkspacePlanOutboxItem) => void;
  isActionPending: boolean;
}) {
  const retryAction = item.actions?.retry_outbox;
  return (
    <li className="border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-words text-sm font-medium text-text-primary dark:text-text-inverse">
            {item.event_type}
          </div>
          <div className="mt-1 flex flex-wrap gap-2 font-mono text-[11px] text-text-muted">
            <span>{shortId(item.id)}</span>
            <span>
              {String(item.attempt_count)} / {String(item.max_attempts)}
            </span>
            {outboxNodeId(item) && <span>node {shortId(outboxNodeId(item))}</span>}
          </div>
          {item.last_error && (
            <p className="mt-2 line-clamp-2 break-words text-xs text-status-text-error dark:text-status-text-error-dark">
              {item.last_error}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <span
            className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${fallbackTone(
              item.status
            )}`}
          >
            {item.status}
          </span>
          {actionEnabled(retryAction) && (
            <button
              type="button"
              onClick={() => {
                onRetry(item);
              }}
              disabled={isActionPending}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              Retry
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

export function BlackboardEntryRow({ entry }: { entry: WorkspacePlanBlackboardEntry }) {
  const preview = asText(entry.value);
  return (
    <li className="border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all font-mono text-xs font-semibold text-text-primary dark:text-text-inverse">
            {entry.key}
          </div>
          {preview && (
            <p className="mt-1 line-clamp-2 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
              {preview}
            </p>
          )}
        </div>
        <span className="shrink-0 rounded-full border border-border-light px-2 py-0.5 font-mono text-[10px] text-text-muted dark:border-border-dark">
          v{String(entry.version)}
        </span>
      </div>
    </li>
  );
}
