import { buildEvidenceBundle } from '../evidence/evidenceBundle';

import type {
  AgentTask,
  Artifact,
  ExecutionNarrativeEntry,
  ToolsetChangedEventData,
} from '@/types/agent';
import type { UnifiedHITLRequest } from '@/types/hitl.unified';
import type { AgentNode } from '@/types/multiAgent';

export type AgentRunMode = 'plan' | 'build' | 'auto' | 'readOnly';
export type AgentRunStatus = 'idle' | 'running' | 'waiting' | 'blocked';
export type AgentRunBlocker = 'doom_loop' | 'hitl' | 'task_failed' | null;
export type AgentRunVerificationState = 'test_evidence' | 'diff_ready' | 'artifacts_ready' | 'none';

export interface AgentRunTaskSummary {
  total: number;
  completed: number;
  inProgress: number;
  pending: number;
  failed: number;
  cancelled: number;
  progressPercent: number;
  currentTask: AgentTask | null;
}

export interface AgentRunAgentSummary {
  total: number;
  running: number;
  pending: number;
  completed: number;
  failed: number;
  stopped: number;
  active: AgentNode | null;
  nodes: AgentNode[];
}

export interface AgentRunEvidenceSummary {
  total: number;
  screenshots: number;
  diffs: number;
  testRuns: number;
  logs: number;
}

export interface AgentRunViewModel {
  conversationId: string | null;
  mode: AgentRunMode;
  status: AgentRunStatus;
  blocker: AgentRunBlocker;
  isPlanMode: boolean;
  isStreaming: boolean;
  taskSummary: AgentRunTaskSummary;
  pendingRequests: UnifiedHITLRequest[];
  pendingRequestCounts: Record<UnifiedHITLRequest['hitlType'], number>;
  agentSummary: AgentRunAgentSummary;
  evidence: AgentRunEvidenceSummary;
  verificationState: AgentRunVerificationState;
  latestNarrative: ExecutionNarrativeEntry | null;
  latestToolsetChange: ToolsetChangedEventData | null;
  sandboxConnectionStatus: string | null;
  currentToolName: string | null;
  doomLoopToolName: string | null;
}

export interface BuildAgentRunViewModelInput {
  conversationId?: string | null | undefined;
  mode: AgentRunMode;
  isPlanMode: boolean;
  isStreaming: boolean;
  tasks: readonly AgentTask[];
  pendingRequests: readonly UnifiedHITLRequest[];
  agentNodes?: ReadonlyMap<string, AgentNode> | undefined;
  artifacts: readonly Artifact[];
  sandboxConnectionStatus?: string | null | undefined;
  currentToolName?: string | null | undefined;
  doomLoopDetected?: { tool_name?: string | undefined } | null | undefined;
  executionNarrative?: readonly ExecutionNarrativeEntry[] | undefined;
  latestToolsetChange?: ToolsetChangedEventData | null | undefined;
}

function summarizeTasks(tasks: readonly AgentTask[]): AgentRunTaskSummary {
  const summary: AgentRunTaskSummary = {
    total: tasks.length,
    completed: 0,
    inProgress: 0,
    pending: 0,
    failed: 0,
    cancelled: 0,
    progressPercent: 0,
    currentTask: null,
  };

  for (const task of tasks) {
    switch (task.status) {
      case 'completed':
        summary.completed += 1;
        break;
      case 'in_progress':
        summary.inProgress += 1;
        summary.currentTask ??= task;
        break;
      case 'failed':
        summary.failed += 1;
        break;
      case 'cancelled':
        summary.cancelled += 1;
        break;
      case 'pending':
      default:
        summary.pending += 1;
        summary.currentTask ??= task;
        break;
    }
  }

  if (!summary.currentTask) {
    summary.currentTask = tasks.find((task) => task.status !== 'completed') ?? null;
  }

  summary.progressPercent =
    summary.total > 0 ? Math.round((summary.completed / summary.total) * 100) : 0;

  return summary;
}

function summarizeAgents(agentNodes?: ReadonlyMap<string, AgentNode>): AgentRunAgentSummary {
  const nodes = agentNodes ? Array.from(agentNodes.values()) : [];
  const summary: AgentRunAgentSummary = {
    total: nodes.length,
    running: 0,
    pending: 0,
    completed: 0,
    failed: 0,
    stopped: 0,
    active: null,
    nodes,
  };

  for (const node of nodes) {
    switch (node.status) {
      case 'running':
        summary.running += 1;
        summary.active ??= node;
        break;
      case 'pending':
        summary.pending += 1;
        break;
      case 'completed':
        summary.completed += 1;
        break;
      case 'failed':
        summary.failed += 1;
        break;
      case 'stopped':
        summary.stopped += 1;
        break;
      default:
        break;
    }
  }

  return summary;
}

function summarizePendingRequests(
  pendingRequests: readonly UnifiedHITLRequest[]
): Record<UnifiedHITLRequest['hitlType'], number> {
  return pendingRequests.reduce<Record<UnifiedHITLRequest['hitlType'], number>>(
    (acc, request) => {
      acc[request.hitlType] += 1;
      return acc;
    },
    {
      clarification: 0,
      decision: 0,
      env_var: 0,
      permission: 0,
    }
  );
}

function deriveStatus(params: {
  isStreaming: boolean;
  pendingCount: number;
  taskSummary: AgentRunTaskSummary;
  agentSummary: AgentRunAgentSummary;
  doomLoopDetected?: { tool_name?: string | undefined } | null | undefined;
}): { status: AgentRunStatus; blocker: AgentRunBlocker } {
  if (params.doomLoopDetected) {
    return { status: 'blocked', blocker: 'doom_loop' };
  }
  if (params.pendingCount > 0) {
    return { status: 'waiting', blocker: 'hitl' };
  }
  if (params.taskSummary.failed > 0 && !params.isStreaming) {
    return { status: 'blocked', blocker: 'task_failed' };
  }
  if (params.isStreaming || params.taskSummary.inProgress > 0 || params.agentSummary.running > 0) {
    return { status: 'running', blocker: null };
  }
  return { status: 'idle', blocker: null };
}

function deriveVerificationState(evidence: AgentRunEvidenceSummary): AgentRunVerificationState {
  if (evidence.testRuns > 0) return 'test_evidence';
  if (evidence.diffs > 0) return 'diff_ready';
  if (evidence.total > 0) return 'artifacts_ready';
  return 'none';
}

export function buildAgentRunViewModel(input: BuildAgentRunViewModelInput): AgentRunViewModel {
  const taskSummary = summarizeTasks(input.tasks);
  const agentSummary = summarizeAgents(input.agentNodes);
  const evidenceBundle = buildEvidenceBundle(input.artifacts);
  const evidence: AgentRunEvidenceSummary = {
    total: evidenceBundle.total,
    screenshots: evidenceBundle.screenshots.length,
    diffs: evidenceBundle.diffs.length,
    testRuns: evidenceBundle.testRuns.length,
    logs: evidenceBundle.logs.length,
  };
  const pendingRequests = input.pendingRequests.filter((request) => request.status === 'pending');
  const pendingRequestCounts = summarizePendingRequests(pendingRequests);
  const { status, blocker } = deriveStatus({
    isStreaming: input.isStreaming,
    pendingCount: pendingRequests.length,
    taskSummary,
    agentSummary,
    doomLoopDetected: input.doomLoopDetected,
  });

  const executionNarrative = input.executionNarrative ?? [];

  return {
    conversationId: input.conversationId ?? null,
    mode: input.mode,
    status,
    blocker,
    isPlanMode: input.isPlanMode,
    isStreaming: input.isStreaming,
    taskSummary,
    pendingRequests,
    pendingRequestCounts,
    agentSummary,
    evidence,
    verificationState: deriveVerificationState(evidence),
    latestNarrative: executionNarrative.length
      ? (executionNarrative[executionNarrative.length - 1] ?? null)
      : null,
    latestToolsetChange: input.latestToolsetChange ?? null,
    sandboxConnectionStatus: input.sandboxConnectionStatus ?? null,
    currentToolName: input.currentToolName ?? null,
    doomLoopToolName: input.doomLoopDetected?.tool_name ?? null,
  };
}
