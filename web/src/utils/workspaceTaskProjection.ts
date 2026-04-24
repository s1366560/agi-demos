import type { WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

export interface PendingLeaderAdjudicationProjection {
  pending: boolean;
  reportType: string;
  reportSummary: string;
  reportArtifacts: string[];
  reportVerifications: string[];
}

export interface PendingLeaderAdjudicationSummary extends PendingLeaderAdjudicationProjection {
  reportTypeLabel: string;
  attemptConversationId?: string;
  attemptNumber?: number;
  workerLabel: string | null;
}

function readNonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function readFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function getTaskMetadata(task: { metadata?: Record<string, unknown> | undefined }): Record<string, unknown> {
  return task.metadata ?? {};
}

export function formatTaskProjectionLabel(value: string): string {
  return value.replace(/_/g, ' ');
}

export function getTaskAttemptConversationId(task: WorkspaceTask): string | undefined {
  const metadata = getTaskMetadata(task);
  return readNonEmptyString(task.current_attempt_conversation_id)
    ?? readNonEmptyString(metadata.current_attempt_conversation_id);
}

export function getTaskAttemptNumber(task: WorkspaceTask): number | undefined {
  const metadata = getTaskMetadata(task);
  return readFiniteNumber(task.current_attempt_number)
    ?? readFiniteNumber(metadata.current_attempt_number);
}

export function getTaskAttemptWorkerBindingId(task: WorkspaceTask): string | undefined {
  const metadata = getTaskMetadata(task);
  return readNonEmptyString(task.current_attempt_worker_binding_id)
    ?? readNonEmptyString(metadata.current_attempt_worker_binding_id);
}

export function getTaskAttemptWorkerAgentId(task: WorkspaceTask): string | undefined {
  const metadata = getTaskMetadata(task);
  return readNonEmptyString(task.current_attempt_worker_agent_id)
    ?? readNonEmptyString(metadata.current_attempt_worker_agent_id);
}

export function resolveTaskAttemptWorkerLabel(
  task: WorkspaceTask,
  agents: WorkspaceAgent[]
): string | null {
  const workerBindingId = getTaskAttemptWorkerBindingId(task) ?? '';
  if (workerBindingId) {
    const binding = agents.find((agent) => agent.id === workerBindingId);
    if (binding) {
      return binding.display_name ?? binding.label ?? binding.agent_id;
    }
  }

  const workerAgentId = getTaskAttemptWorkerAgentId(task) ?? '';
  if (workerAgentId) {
    const binding = agents.find((agent) => agent.agent_id === workerAgentId);
    if (binding) {
      return binding.display_name ?? binding.label ?? binding.agent_id;
    }
    return workerAgentId;
  }

  return null;
}

export function hasPendingLeaderAdjudication(task: WorkspaceTask): boolean {
  const metadata = getTaskMetadata(task);
  return (
    task.pending_leader_adjudication === true
    || metadata.pending_leader_adjudication === true
  );
}

export function getPendingLeaderAdjudicationProjection(
  task: WorkspaceTask
): PendingLeaderAdjudicationProjection {
  const metadata = getTaskMetadata(task);
  const explicitArtifacts = Array.isArray(task.last_worker_report_artifacts)
    ? task.last_worker_report_artifacts
    : null;
  const explicitVerifications = Array.isArray(task.last_worker_report_verifications)
    ? task.last_worker_report_verifications
    : null;
  return {
    pending: hasPendingLeaderAdjudication(task),
    reportType:
      readNonEmptyString(task.last_worker_report_type)
      ?? readNonEmptyString(metadata.last_worker_report_type)
      ?? '',
    reportSummary:
      readNonEmptyString(task.last_worker_report_summary)
      ?? readNonEmptyString(metadata.last_worker_report_summary)
      ?? '',
    reportArtifacts: explicitArtifacts
      ? explicitArtifacts
          .filter((item): item is string => typeof item === 'string' && item.length > 0)
          .slice(0, 3)
      : Array.isArray(metadata.last_worker_report_artifacts)
      ? metadata.last_worker_report_artifacts
          .filter((item): item is string => typeof item === 'string' && item.length > 0)
          .slice(0, 3)
      : [],
    reportVerifications: explicitVerifications
      ? explicitVerifications
          .filter((item): item is string => typeof item === 'string' && item.length > 0)
          .slice(0, 3)
      : Array.isArray(metadata.last_worker_report_verifications)
      ? metadata.last_worker_report_verifications
          .filter((item): item is string => typeof item === 'string' && item.length > 0)
          .slice(0, 3)
      : [],
  };
}

export function getPendingLeaderAdjudicationSummary(
  task: WorkspaceTask,
  agents: WorkspaceAgent[]
): PendingLeaderAdjudicationSummary {
  const projection = getPendingLeaderAdjudicationProjection(task);

  return {
    ...projection,
    reportTypeLabel: projection.reportType ? formatTaskProjectionLabel(projection.reportType) : '',
    attemptConversationId: getTaskAttemptConversationId(task),
    attemptNumber: getTaskAttemptNumber(task),
    workerLabel: resolveTaskAttemptWorkerLabel(task, agents),
  };
}
