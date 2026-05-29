import { describe, expect, it } from 'vitest';

import { buildWorkspaceAgentNodes } from '@/components/agent/multiAgent/workspaceAgentPanelModel';

import type { WorkspaceAgent, WorkspacePlanSnapshot, WorkspaceTask } from '@/types/workspace';

function workspaceAgent(overrides: Partial<WorkspaceAgent>): WorkspaceAgent {
  return {
    id: 'binding-builder',
    workspace_id: 'workspace-1',
    agent_id: 'agent-builder',
    display_name: 'Workspace Builder',
    label: 'Builder',
    config: { workspace_role: 'execution_worker' },
    is_active: true,
    status: 'idle',
    created_at: '2026-05-29T08:00:00Z',
    ...overrides,
  };
}

function workspaceTask(overrides: Partial<WorkspaceTask>): WorkspaceTask {
  return {
    id: 'task-1',
    workspace_id: 'workspace-1',
    title: 'Implement swarm service',
    status: 'in_progress',
    metadata: {},
    created_at: '2026-05-29T09:00:00Z',
    ...overrides,
  };
}

function snapshot(): WorkspacePlanSnapshot {
  return {
    workspace_id: 'workspace-1',
    plan: null,
    blackboard: [],
    outbox: [],
    events: [
      {
        id: 'event-1',
        plan_id: 'plan-1',
        workspace_id: 'workspace-1',
        event_type: 'supervisor_decision_completed',
        source: 'supervisor',
        payload: {},
        created_at: '2026-05-29T09:30:00Z',
      },
    ],
  };
}

describe('buildWorkspaceAgentNodes', () => {
  it('projects workspace roster and current attempts into the multi-agent tree', () => {
    const nodes = buildWorkspaceAgentNodes({
      workspaceId: 'workspace-1',
      conversationId: 'workspace-contract:supervisor-decision:tenant:project:workspace:plan:node',
      agents: [
        workspaceAgent({ id: 'binding-builder', agent_id: 'agent-builder' }),
        workspaceAgent({
          id: 'binding-verifier',
          agent_id: 'agent-verifier',
          display_name: 'Workspace Verifier',
          label: 'Verifier',
          config: { workspace_role: 'verifier' },
          status: 'running',
        }),
      ],
      tasks: [
        workspaceTask({
          current_attempt_id: 'attempt-21',
          current_attempt_number: 21,
          current_attempt_conversation_id: 'conversation-attempt-21',
          current_attempt_worker_binding_id: 'binding-builder',
          current_attempt_worker_agent_id: 'agent-builder',
          last_attempt_status: 'awaiting_leader_adjudication',
          last_worker_report_summary: 'Worker report summary',
          last_worker_report_artifacts: ['SANDBOX-PREVIEW-EVIDENCE.md'],
        }),
      ],
      snapshot: snapshot(),
    });

    const supervisor = nodes.get('workspace-supervisor:workspace-1');
    const builder = nodes.get('workspace-agent:binding-builder');
    const verifier = nodes.get('workspace-agent:binding-verifier');
    const attempt = nodes.get('workspace-attempt:attempt-21');

    expect(supervisor).toMatchObject({
      name: 'Workspace Supervisor',
      sessionId: 'workspace-contract:supervisor-decision:tenant:project:workspace:plan:node',
    });
    expect(supervisor?.children).toEqual(
      expect.arrayContaining([
        'workspace-agent:binding-builder',
        'workspace-agent:binding-verifier',
      ])
    );

    expect(builder).toMatchObject({
      name: 'Workspace Builder',
      parentAgentId: 'workspace-supervisor:workspace-1',
      taskSummary: 'execution_worker',
    });
    expect(builder?.children).toContain('workspace-attempt:attempt-21');

    expect(verifier).toMatchObject({
      name: 'Workspace Verifier',
      status: 'running',
      taskSummary: 'verifier',
    });

    expect(attempt).toMatchObject({
      name: 'Attempt #21',
      parentAgentId: 'workspace-agent:binding-builder',
      sessionId: 'conversation-attempt-21',
      status: 'running',
      taskSummary: 'Implement swarm service',
      result: 'Worker report summary',
      artifacts: ['SANDBOX-PREVIEW-EVIDENCE.md'],
    });
  });

  it('returns no synthetic nodes when there is no active workspace', () => {
    const nodes = buildWorkspaceAgentNodes({
      workspaceId: null,
      conversationId: null,
      agents: [],
      tasks: [],
      snapshot: null,
    });

    expect(nodes.size).toBe(0);
  });
});
