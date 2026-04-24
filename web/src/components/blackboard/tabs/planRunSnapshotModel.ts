import type {
  WorkspacePlanActionCapability,
  WorkspacePlanEvent,
  WorkspacePlanNode,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
} from '@/types/workspace';

export type NodeFilter = 'all' | 'running' | 'blocked' | 'verifying' | 'done' | 'recovery';
export type NodeActionId = 'request_replan' | 'reopen_blocked';

export const FILTERS: Array<{ id: NodeFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'verifying', label: 'Verifying' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'done', label: 'Done' },
  { id: 'recovery', label: 'Recovery' },
];

const NODE_TONE: Record<string, string> = {
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
  dead_letter:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  dead: 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
};

export function fallbackTone(status: string): string {
  return (
    OUTBOX_TONE[status] ??
    NODE_TONE[status] ??
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
  );
}

export function shortId(id: string | null | undefined): string {
  if (!id) {
    return '';
  }
  return id.length > 12 ? `${id.slice(0, 7)}...${id.slice(-4)}` : id;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return 'n/a';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatRelative(value: Date | null): string {
  if (!value) {
    return 'never';
  }
  const seconds = Math.max(0, Math.round((Date.now() - value.getTime()) / 1000));
  if (seconds < 60) {
    return `${String(seconds)}s ago`;
  }
  const minutes = Math.round(seconds / 60);
  return `${String(minutes)}m ago`;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function asText(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (value === null || value === undefined) {
    return '';
  }
  try {
    return JSON.stringify(value);
  } catch {
    return Object.prototype.toString.call(value);
  }
}

export function eventLabel(event: WorkspacePlanEvent): string {
  if (event.event_type === 'worker_report_terminal') {
    return 'Worker submitted result';
  }
  if (event.event_type === 'verification_completed') {
    const payload = asRecord(event.payload);
    if (payload.passed === true) {
      return 'Verifier accepted';
    }
    if (payload.hard_fail === true) {
      return 'Verifier blocked';
    }
    return 'Verifier requested replan';
  }
  if (event.event_type === 'operator_retry_outbox') {
    return 'Operator retried queue job';
  }
  if (event.event_type === 'operator_replan_requested') {
    return 'Operator requested replan';
  }
  if (event.event_type === 'operator_node_reopened') {
    return 'Operator reopened node';
  }
  if (event.event_type === 'supervisor_tick') {
    return 'Supervisor scheduled work';
  }
  return event.event_type;
}

export function eventSummary(event: WorkspacePlanEvent): string {
  const payload = asRecord(event.payload);
  return asText(payload.summary ?? payload.reason ?? payload.error ?? payload.message);
}

export function outboxNodeId(item: WorkspacePlanOutboxItem): string {
  return asText(asRecord(item.payload).node_id);
}

export function countDone(nodes: WorkspacePlanNode[]): number {
  return nodes.filter((node) => node.intent === 'done').length;
}

export function planStage(snapshot: WorkspacePlanSnapshot | null): string {
  const plan = snapshot?.plan;
  if (!plan) {
    return 'Not started';
  }
  const nodes = plan.nodes;
  if (plan.status === 'completed' || (nodes.length > 0 && countDone(nodes) === nodes.length)) {
    return 'Complete';
  }
  if (
    nodes.some((node) => node.intent === 'blocked') ||
    snapshot.outbox.some((item) => item.status === 'failed' || item.status === 'dead_letter')
  ) {
    return 'Recovery needed';
  }
  if (nodes.some((node) => node.execution === 'verifying' || node.execution === 'reported')) {
    return 'Verifying';
  }
  if (nodes.some((node) => node.execution === 'running' || node.execution === 'dispatched')) {
    return 'Executing';
  }
  return 'Planning';
}

export function matchesFilter(node: WorkspacePlanNode, filter: NodeFilter): boolean {
  if (filter === 'all') {
    return true;
  }
  if (filter === 'running') {
    return node.execution === 'running' || node.execution === 'dispatched';
  }
  if (filter === 'blocked') {
    return node.intent === 'blocked';
  }
  if (filter === 'verifying') {
    return node.execution === 'reported' || node.execution === 'verifying';
  }
  if (filter === 'done') {
    return node.intent === 'done';
  }
  return (
    node.intent === 'blocked' ||
    node.execution === 'reported' ||
    node.execution === 'verifying' ||
    Boolean(node.actions?.request_replan?.enabled)
  );
}

export function actionEnabled(action: WorkspacePlanActionCapability | undefined): boolean {
  return Boolean(action?.enabled);
}
