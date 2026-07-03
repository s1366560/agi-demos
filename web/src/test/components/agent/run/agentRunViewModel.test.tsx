import { describe, expect, it, vi } from 'vitest';

import { fireEvent, render, screen } from '@/test/utils';

import { RunStatusStrip } from '@/components/agent/run/RunStatusStrip';
import { buildAgentRunViewModel } from '@/components/agent/run/agentRunViewModel';

import type { AgentTask, Artifact, ExecutionNarrativeEntry } from '@/types/agent';
import type { UnifiedHITLRequest } from '@/types/hitl.unified';
import type { AgentNode } from '@/types/multiAgent';

function task(id: string, status: AgentTask['status'], content = 'Implement UI'): AgentTask {
  return {
    id,
    conversation_id: 'conv-1',
    content,
    status,
    priority: 'medium',
    order_index: 1,
    created_at: '2026-07-03T00:00:00Z',
    updated_at: '2026-07-03T00:01:00Z',
  };
}

function artifact(id: string, filename: string, mimeType: string, sourceTool?: string): Artifact {
  return {
    id,
    projectId: 'project-1',
    tenantId: 'tenant-1',
    conversationId: 'conv-1',
    filename,
    mimeType,
    category: mimeType.startsWith('image/') ? 'image' : 'code',
    sizeBytes: 1024,
    status: 'ready',
    sourceTool,
    createdAt: '2026-07-03T00:02:00Z',
  };
}

function hitl(id: string, hitlType: UnifiedHITLRequest['hitlType']): UnifiedHITLRequest {
  return {
    requestId: id,
    hitlType,
    conversationId: 'conv-1',
    status: 'pending',
    timeoutSeconds: 300,
    createdAt: '2026-07-03T00:03:00Z',
    question: 'Approve this action?',
    permissionData:
      hitlType === 'permission'
        ? {
            toolName: 'bash',
            action: 'run command',
            riskLevel: 'medium',
            details: {},
            allowRemember: false,
            context: {},
          }
        : undefined,
  };
}

describe('agent run view model', () => {
  it('summarizes tasks, HITL, agents, and evidence into a run state', () => {
    const agentNodes = new Map<string, AgentNode>([
      [
        'agent-1',
        {
          agentId: 'agent-1',
          name: 'Verifier',
          parentAgentId: null,
          sessionId: 'session-1',
          status: 'running',
          taskSummary: 'Verify UI',
          result: null,
          success: null,
          artifacts: [],
          children: [],
          createdAt: 1,
          lastUpdateAt: 2,
        },
      ],
    ]);
    const narrative: ExecutionNarrativeEntry[] = [
      {
        id: 'trace-1',
        stage: 'verification',
        summary: 'Checking evidence bundle',
        timestamp: Date.now(),
      },
    ];

    const run = buildAgentRunViewModel({
      conversationId: 'conv-1',
      mode: 'plan',
      isPlanMode: true,
      isStreaming: true,
      tasks: [task('task-1', 'completed'), task('task-2', 'in_progress', 'Wire status strip')],
      pendingRequests: [hitl('hitl-1', 'permission')],
      agentNodes,
      artifacts: [
        artifact('artifact-1', 'changes.diff', 'text/x-diff'),
        artifact('artifact-2', 'vitest.jsonl', 'application/x-ndjson', 'run_tests'),
      ],
      executionNarrative: narrative,
    });

    expect(run.status).toBe('waiting');
    expect(run.blocker).toBe('hitl');
    expect(run.taskSummary.progressPercent).toBe(50);
    expect(run.taskSummary.currentTask?.content).toBe('Wire status strip');
    expect(run.pendingRequestCounts.permission).toBe(1);
    expect(run.agentSummary.running).toBe(1);
    expect(run.agentSummary.active?.name).toBe('Verifier');
    expect(run.evidence.testRuns).toBe(1);
    expect(run.evidence.diffs).toBe(1);
    expect(run.verificationState).toBe('test_evidence');
    expect(run.latestNarrative?.stage).toBe('verification');
  });
});

describe('RunStatusStrip', () => {
  it('renders status, checkpoint, evidence, and inspector actions', () => {
    const onOpenInspector = vi.fn();
    const onOpenEvidence = vi.fn();
    const run = buildAgentRunViewModel({
      conversationId: 'conv-1',
      mode: 'build',
      isPlanMode: false,
      isStreaming: true,
      tasks: [task('task-1', 'in_progress', 'Verify rendered flow')],
      pendingRequests: [],
      artifacts: [artifact('artifact-1', 'screenshot.png', 'image/png')],
    });

    render(
      <RunStatusStrip
        run={run}
        onStop={vi.fn()}
        onOpenInspector={onOpenInspector}
        onOpenEvidence={onOpenEvidence}
      />
    );

    expect(screen.getByTestId('run-status-strip')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText(/Verify rendered flow/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Inspector/i }));
    expect(onOpenInspector).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /Artifacts ready/i }));
    expect(onOpenEvidence).toHaveBeenCalledTimes(1);
  });
});
