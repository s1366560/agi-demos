import type {
  WorkspacePlanActionCapability,
  WorkspacePlanBlackboardEntry,
  WorkspacePlanDeliverySummary,
  WorkspacePlanEvent,
  WorkspacePlanNode,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
  WorkspaceTask,
} from '@/types/workspace';

export type NodeFilter = 'all' | 'running' | 'blocked' | 'verifying' | 'done' | 'recovery';
export type NodeActionId = 'request_replan' | 'reopen_blocked' | 'accept_with_human_review';
export type IterationStatus = 'active' | 'completed' | 'blocked' | 'planned';

export interface IterationInteractionStats {
  total: number;
  worker: number;
  verifier: number;
  supervisor: number;
  operator: number;
  other: number;
  retries: number;
  failed: number;
}

export interface IterationOutputSummary {
  artifacts: string[];
  evidenceRefs: string[];
  changedFiles: string[];
  pipelineRefs: string[];
  commitRefs: string[];
  blackboardKeys: string[];
  total: number;
}

export interface WorkspacePlanIterationRun {
  index: number;
  status: IterationStatus;
  sprintGoal: string;
  reviewSummary: string;
  nextSprintGoal: string;
  startedAt: string;
  updatedAt: string;
  completedAt: string;
  nodes: WorkspacePlanNode[];
  linkedTasks: WorkspaceTask[];
  events: WorkspacePlanEvent[];
  outbox: WorkspacePlanOutboxItem[];
  outputs: IterationOutputSummary;
  interactions: IterationInteractionStats;
  attempts: Record<string, number>;
  verification: Record<string, number>;
  repairTurns: Array<Record<string, unknown>>;
  carryoverNodeIds: string[];
  counts: {
    total: number;
    done: number;
    running: number;
    blocked: number;
    verifying: number;
    carriedOver?: number;
  };
}

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

function uniqueStrings(items: Array<string | null | undefined>): string[] {
  return Array.from(new Set(items.filter((item): item is string => Boolean(item))));
}

function metadataStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

function nodeEvidenceArtifacts(node: WorkspacePlanNode): string[] {
  return node.evidence_bundle?.artifacts ?? [];
}

function nodeEvidenceRefs(node: WorkspacePlanNode): string[] {
  return node.evidence_bundle?.evidence_refs ?? [];
}

function nodeChangedFiles(node: WorkspacePlanNode): string[] {
  return node.evidence_bundle?.changed_files ?? nodeWriteSet(node);
}

function nodePipelineRefs(node: WorkspacePlanNode): string[] {
  return node.evidence_bundle?.pipeline_refs ?? [];
}

export function nodeWriteSet(node: WorkspacePlanNode): string[] {
  const value = asRecord(node.metadata).write_set;
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

export function iterationNodeIndex(node: WorkspacePlanNode): number {
  const value = asRecord(node.metadata).iteration_index;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value === 'string' && /^\d+$/.test(value)) {
    return Math.max(1, Number(value));
  }
  return 1;
}

function iterationNodeIds(nodes: WorkspacePlanNode[]): Set<string> {
  return new Set(nodes.map((node) => node.id));
}

function iterationAttemptIds(nodes: WorkspacePlanNode[]): Set<string> {
  return new Set(nodes.map((node) => node.current_attempt_id).filter(Boolean) as string[]);
}

function eventBelongsToNodes(event: WorkspacePlanEvent, nodes: WorkspacePlanNode[]): boolean {
  const nodeIds = iterationNodeIds(nodes);
  const attemptIds = iterationAttemptIds(nodes);
  return Boolean(
    (event.node_id && nodeIds.has(event.node_id)) ||
    (event.attempt_id && attemptIds.has(event.attempt_id))
  );
}

function outboxBelongsToNodes(item: WorkspacePlanOutboxItem, nodes: WorkspacePlanNode[]): boolean {
  const nodeIds = iterationNodeIds(nodes);
  const attemptIds = iterationAttemptIds(nodes);
  const payload = asRecord(item.payload);
  const nodeId = outboxNodeId(item);
  const attemptId = asText(payload.attempt_id ?? payload.workspace_attempt_id);
  return Boolean((nodeId && nodeIds.has(nodeId)) || (attemptId && attemptIds.has(attemptId)));
}

function interactionBucket(source: string, eventType: string): keyof IterationInteractionStats {
  const text = `${source} ${eventType}`.toLowerCase();
  if (text.includes('worker')) {
    return 'worker';
  }
  if (text.includes('verifier') || text.includes('verification')) {
    return 'verifier';
  }
  if (text.includes('supervisor') || text.includes('dispatch')) {
    return 'supervisor';
  }
  if (text.includes('operator')) {
    return 'operator';
  }
  return 'other';
}

export function iterationInteractionStats(
  events: WorkspacePlanEvent[],
  outbox: WorkspacePlanOutboxItem[],
  nodes: WorkspacePlanNode[]
): IterationInteractionStats {
  const stats: IterationInteractionStats = {
    total: 0,
    worker: 0,
    verifier: 0,
    supervisor: 0,
    operator: 0,
    other: 0,
    retries: 0,
    failed: 0,
  };
  const relatedEvents = events.filter((event) => eventBelongsToNodes(event, nodes));
  const relatedOutbox = outbox.filter((item) => outboxBelongsToNodes(item, nodes));
  for (const event of relatedEvents) {
    const bucket = interactionBucket(event.source, event.event_type);
    stats[bucket] += 1;
  }
  for (const item of relatedOutbox) {
    const bucket = interactionBucket(asText(item.metadata.source), item.event_type);
    stats[bucket] += 1;
    stats.retries += Math.max(0, item.attempt_count - 1);
    if (item.status === 'failed' || item.status === 'dead_letter' || item.status === 'dead') {
      stats.failed += 1;
    }
  }
  stats.total = relatedEvents.length + relatedOutbox.length;
  return stats;
}

export function iterationOutputs(
  nodes: WorkspacePlanNode[],
  blackboard: WorkspacePlanBlackboardEntry[],
  delivery: WorkspacePlanDeliverySummary | null | undefined
): IterationOutputSummary {
  const metadata = nodes.map((node) => asRecord(node.metadata));
  const artifacts = uniqueStrings(nodes.flatMap(nodeEvidenceArtifacts));
  const evidenceRefs = uniqueStrings(nodes.flatMap(nodeEvidenceRefs));
  const changedFiles = uniqueStrings(nodes.flatMap(nodeChangedFiles));
  const pipelineRefs = uniqueStrings(nodes.flatMap(nodePipelineRefs));
  const commitRefs = uniqueStrings(
    metadata.flatMap((item) => [
      asText(item.commit_ref),
      asText(item.commitRef),
      asText(item.latest_commit_ref),
      ...metadataStringList(item.commit_refs),
    ])
  );
  const blackboardKeys = uniqueStrings(
    blackboard.filter((entry) => entry.key.startsWith('artifact.')).map((entry) => entry.key)
  );
  if (delivery?.latest_run?.commit_ref) {
    commitRefs.push(delivery.latest_run.commit_ref);
  }
  const totals = new Set([
    ...artifacts,
    ...evidenceRefs,
    ...changedFiles,
    ...pipelineRefs,
    ...commitRefs,
    ...blackboardKeys,
  ]);
  return {
    artifacts,
    evidenceRefs,
    changedFiles,
    pipelineRefs,
    commitRefs: uniqueStrings(commitRefs),
    blackboardKeys,
    total: totals.size,
  };
}

export function iterationCarryover(nodes: WorkspacePlanNode[]): string[] {
  return nodes.filter((node) => node.intent !== 'done').map((node) => node.id);
}

function iterationStatus(
  index: number,
  nodes: WorkspacePlanNode[],
  snapshot: WorkspacePlanSnapshot
): IterationStatus {
  const current = snapshot.iteration?.current_iteration ?? 1;
  if (index === current) {
    return snapshot.iteration?.loop_status === 'completed' ? 'completed' : 'active';
  }
  if (
    snapshot.iteration?.completed_iterations.includes(index) ||
    (nodes.length > 0 && nodes.every((node) => node.intent === 'done'))
  ) {
    return 'completed';
  }
  if (nodes.some((node) => node.intent === 'blocked')) {
    return 'blocked';
  }
  return 'planned';
}

function iterationDates(nodes: WorkspacePlanNode[]) {
  const sortedCreated = nodes
    .map((node) => node.created_at)
    .filter(Boolean)
    .sort();
  const sortedUpdated = nodes
    .map((node) => node.updated_at ?? node.created_at)
    .filter(Boolean)
    .sort();
  const sortedCompleted = nodes
    .map((node) => node.completed_at)
    .filter(Boolean)
    .sort();
  return {
    startedAt: sortedCreated[0] ?? '',
    updatedAt: sortedUpdated.at(-1) ?? '',
    completedAt: sortedCompleted.at(-1) ?? '',
  };
}

function numberFromRecord(record: Record<string, number> | undefined, key: string): number {
  const value = record?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function listFromRecord(record: Record<string, string[]> | undefined, key: string): string[] {
  const value = record?.[key];
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}

function normalizeBackendIterationRuns(
  snapshot: WorkspacePlanSnapshot,
  tasks: WorkspaceTask[]
): WorkspacePlanIterationRun[] {
  const backendRuns = snapshot.iteration_runs ?? [];
  if (backendRuns.length === 0 || !snapshot.plan) {
    return [];
  }
  const tasksById = new Map(tasks.map((task) => [task.id, task]));
  const nodesById = new Map(snapshot.plan.nodes.map((node) => [node.id, node]));
  return backendRuns.map((run) => {
    const nodeIds = new Set(run.node_ids ?? []);
    const nodes = snapshot.plan?.nodes.filter((node) => nodeIds.has(node.id)) ?? [];
    const taskIds = uniqueStrings(nodes.map((node) => node.workspace_task_id));
    const outputs: IterationOutputSummary = {
      artifacts: listFromRecord(run.deliverables, 'artifacts'),
      evidenceRefs: listFromRecord(run.deliverables, 'evidence_refs'),
      changedFiles: listFromRecord(run.deliverables, 'changed_files'),
      pipelineRefs: listFromRecord(run.deliverables, 'pipeline_refs'),
      commitRefs: listFromRecord(run.deliverables, 'commit_refs'),
      blackboardKeys: listFromRecord(run.deliverables, 'blackboard_keys'),
      total: new Set(Object.values(run.deliverables ?? {}).flat()).size,
    };
    const interactions: IterationInteractionStats = {
      total: numberFromRecord(run.interaction_counts, 'total'),
      worker: numberFromRecord(run.interaction_counts, 'worker'),
      verifier: numberFromRecord(run.interaction_counts, 'verifier'),
      supervisor: numberFromRecord(run.interaction_counts, 'supervisor'),
      operator: numberFromRecord(run.interaction_counts, 'operator'),
      other:
        numberFromRecord(run.interaction_counts, 'other') +
        numberFromRecord(run.interaction_counts, 'recovery'),
      retries: numberFromRecord(run.interaction_counts, 'retries'),
      failed: numberFromRecord(run.interaction_counts, 'failed'),
    };
    return {
      index: run.iteration_index,
      status: (['active', 'completed', 'blocked', 'planned'].includes(run.status)
        ? run.status
        : run.status === 'running'
          ? 'active'
          : 'planned') as IterationStatus,
      sprintGoal: run.sprint_goal,
      reviewSummary: run.review_summary,
      nextSprintGoal: run.next_sprint_goal,
      startedAt: run.time_range?.started_at ?? '',
      updatedAt: run.time_range?.updated_at ?? '',
      completedAt: run.time_range?.completed_at ?? '',
      nodes: nodes.length > 0 ? nodes : Array.from(nodeIds).flatMap((id) => nodesById.get(id) ?? []),
      linkedTasks: taskIds.map((taskId) => tasksById.get(taskId)).filter(Boolean) as WorkspaceTask[],
      events: snapshot.events.filter((event) => eventBelongsToNodes(event, nodes)),
      outbox: snapshot.outbox.filter((item) => outboxBelongsToNodes(item, nodes)),
      outputs,
      interactions,
      attempts: run.attempt_counts ?? {},
      verification: run.verification_summary ?? {},
      repairTurns: run.repair_turns ?? [],
      carryoverNodeIds: run.carryover_node_ids ?? [],
      counts: {
        total: numberFromRecord(run.task_counts, 'total'),
        done: numberFromRecord(run.task_counts, 'done'),
        running: numberFromRecord(run.task_counts, 'running'),
        blocked: numberFromRecord(run.task_counts, 'blocked'),
        verifying: numberFromRecord(run.task_counts, 'verifying'),
        carriedOver: numberFromRecord(run.task_counts, 'carried_over'),
      },
    };
  });
}

export function buildIterationRuns(
  snapshot: WorkspacePlanSnapshot | null,
  tasks: WorkspaceTask[] = []
): WorkspacePlanIterationRun[] {
  if (!snapshot?.plan) {
    return [];
  }
  const backendRuns = normalizeBackendIterationRuns(snapshot, tasks);
  if (backendRuns.length > 0) {
    return backendRuns;
  }
  const runnableNodes = snapshot.plan.nodes.filter(
    (node) => node.kind === 'task' || node.kind === 'verify'
  );
  const indexes = new Set<number>([
    snapshot.iteration?.current_iteration ?? 1,
    ...(snapshot.iteration?.completed_iterations ?? []),
    ...(snapshot.iteration?.history ?? []).map((item) => item.iteration_index),
    ...runnableNodes.map(iterationNodeIndex),
  ]);
  const tasksById = new Map(tasks.map((task) => [task.id, task]));
  return Array.from(indexes)
    .filter((index) => index > 0)
    .sort((a, b) => a - b)
    .map((index) => {
      const nodes = runnableNodes.filter((node) => iterationNodeIndex(node) === index);
      const history = snapshot.iteration?.history.find((item) => item.iteration_index === index);
      const isCurrent = index === snapshot.iteration?.current_iteration;
      const events = snapshot.events.filter((event) => eventBelongsToNodes(event, nodes));
      const outbox = snapshot.outbox.filter((item) => outboxBelongsToNodes(item, nodes));
      const dates = iterationDates(nodes);
      return {
        index,
        status: iterationStatus(index, nodes, snapshot),
        sprintGoal: isCurrent
          ? (snapshot.iteration?.current_sprint_goal ?? '')
          : history?.next_sprint_goal || history?.summary || '',
        reviewSummary: isCurrent
          ? (snapshot.iteration?.review_summary ?? history?.summary ?? '')
          : (history?.summary ?? ''),
        nextSprintGoal: history?.next_sprint_goal ?? '',
        ...dates,
        nodes,
        linkedTasks: uniqueStrings(nodes.map((node) => node.workspace_task_id))
          .map((taskId) => tasksById.get(taskId))
          .filter((task): task is WorkspaceTask => Boolean(task)),
        events,
        outbox,
        outputs: iterationOutputs(nodes, snapshot.blackboard, snapshot.delivery),
        interactions: iterationInteractionStats(snapshot.events, snapshot.outbox, nodes),
        attempts: {},
        verification: {},
        repairTurns: [],
        carryoverNodeIds: iterationCarryover(nodes),
        counts: {
          total: nodes.length,
          done: nodes.filter((node) => node.intent === 'done').length,
          running: nodes.filter(
            (node) => node.execution === 'running' || node.execution === 'dispatched'
          ).length,
          blocked: nodes.filter((node) => node.intent === 'blocked').length,
          verifying: nodes.filter(
            (node) => node.execution === 'reported' || node.execution === 'verifying'
          ).length,
        },
      };
    });
}

export function criterionSummary(node: WorkspacePlanNode): string {
  if (node.acceptance_criteria.length === 0) {
    return 'No checks';
  }
  const kinds = node.acceptance_criteria.map((criterion) => criterion.kind);
  return Array.from(new Set(kinds)).join(', ');
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
  if (event.event_type === 'dispatch_deferred_write_conflict') {
    return 'Dispatch deferred';
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

export function rootGoalNeedsClosure(snapshot: WorkspacePlanSnapshot | null): boolean {
  const root = snapshot?.root_goal;
  return Boolean(root && root.status !== 'done');
}

export function planStage(snapshot: WorkspacePlanSnapshot | null): string {
  const plan = snapshot?.plan;
  if (!plan) {
    return 'Not started';
  }
  const nodes = plan.nodes;
  if (rootGoalNeedsClosure(snapshot)) {
    return snapshot.root_goal?.completion_blocker_reason ? 'Root closure needed' : 'Closing root';
  }
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
