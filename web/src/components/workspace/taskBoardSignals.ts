import { formatTaskProjectionLabel } from '@/utils/workspaceTaskProjection';

import type { WorkspaceTask } from '@/types/workspace';

export interface RootGoalDisplayState {
  isRootGoal: boolean;
  goalHealth: string;
  remediationStatus: string;
  verificationGrade: string;
}

export interface TaskObservabilityState {
  codeRoot: string;
  agentsDigest: string;
  loadedAgentsCount: number;
  launchState: string;
  durableVerdict: string;
  missingConversation: boolean;
}

export function getRootGoalDisplayState(
  metadata: Record<string, unknown> | undefined
): RootGoalDisplayState {
  const safeMetadata = metadata ?? {};
  const taskRole = typeof safeMetadata.task_role === 'string' ? safeMetadata.task_role : '';
  const goalEvidence =
    safeMetadata.goal_evidence && typeof safeMetadata.goal_evidence === 'object'
      ? (safeMetadata.goal_evidence as Record<string, unknown>)
      : null;

  return {
    isRootGoal: taskRole === 'goal_root',
    goalHealth: typeof safeMetadata.goal_health === 'string' ? safeMetadata.goal_health : '',
    remediationStatus:
      typeof safeMetadata.remediation_status === 'string' ? safeMetadata.remediation_status : '',
    verificationGrade:
      goalEvidence && typeof goalEvidence.verification_grade === 'string'
        ? goalEvidence.verification_grade
        : '',
  };
}

export function formatMetadataLabel(value: string): string {
  return formatTaskProjectionLabel(value);
}

export function getTaskObservabilityState(task: WorkspaceTask): TaskObservabilityState {
  const metadata = Object(task.metadata) as Record<string, unknown>;
  const codeContext =
    metadata.code_context && typeof metadata.code_context === 'object'
      ? (metadata.code_context as Record<string, unknown>)
      : null;
  const loadedAgentsFiles = Array.isArray(codeContext?.loaded_agents_files)
    ? codeContext.loaded_agents_files.filter((item): item is string => typeof item === 'string')
    : [];
  const currentAttemptId =
    typeof metadata.current_attempt_id === 'string'
      ? metadata.current_attempt_id
      : task.current_attempt_id;
  const attemptConversationId =
    typeof metadata.current_attempt_conversation_id === 'string'
      ? metadata.current_attempt_conversation_id
      : task.current_attempt_conversation_id;

  return {
    codeRoot:
      typeof codeContext?.sandbox_code_root === 'string'
        ? codeContext.sandbox_code_root
        : typeof metadata.sandbox_code_root === 'string'
          ? metadata.sandbox_code_root
          : '',
    agentsDigest: typeof codeContext?.agents_digest === 'string' ? codeContext.agents_digest : '',
    loadedAgentsCount: loadedAgentsFiles.length,
    launchState: typeof metadata.launch_state === 'string' ? metadata.launch_state : '',
    durableVerdict:
      typeof metadata.durable_plan_verdict === 'string' ? metadata.durable_plan_verdict : '',
    missingConversation: Boolean(
      task.status === 'in_progress' && currentAttemptId && !attemptConversationId
    ),
  };
}
