import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StatusTab } from '@/components/blackboard/tabs/StatusTab';
import { workspacePlanService } from '@/services/workspaceService';
import { render, screen } from '@/test/utils';

vi.mock('@/services/workspaceService', () => ({
  workspacePlanService: {
    getSnapshot: vi.fn(),
  },
}));

describe('StatusTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValue({
      workspace_id: 'ws-1',
      plan: null,
      blackboard: [],
      outbox: [],
      events: [],
    });
  });

  it('renders binding-aware worker label for pending adjudication tasks', async () => {
    render(
      <StatusTab
        stats={{
          completionRatio: 50,
          discussions: 1,
          activeAgents: 1,
          pendingAdjudicationTasks: 1,
        }}
        topologyEdges={[]}
        agents={[
          {
            id: 'binding-1',
            workspace_id: 'ws-1',
            agent_id: 'worker-a',
            display_name: 'Worker A',
            is_active: true,
            created_at: '2026-04-23T00:00:00Z',
          },
        ]}
        tasks={[
          {
            id: 'task-1',
            workspace_id: 'ws-1',
            title: 'Draft checklist',
            status: 'in_progress',
            created_at: '2026-04-23T00:00:00Z',
            metadata: {
              pending_leader_adjudication: true,
              last_worker_report_type: 'completed',
              last_worker_report_summary: 'Checklist drafted',
              current_attempt_worker_binding_id: 'binding-1',
            },
          },
        ]}
        workspaceId="ws-1"
        projectId="p-1"
        tenantId="t-1"
        statusBadgeTone={() => 'bg-green-500'}
      />
    );

    expect(
      screen.getAllByText((content, node) => {
        const text = node?.textContent ?? content;
        return text.includes('Worker A') && text.includes('blackboard.pendingAdjudicationWorker');
      })[0]
    ).toBeInTheDocument();
    const boundaryBadge = screen
      .getByText('blackboard.pendingAdjudicationSurfaceHint')
      .closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');

    const derivedBadge = screen.getByText('blackboard.statusOverviewDerivedHint').closest('div');
    expect(derivedBadge).toHaveAttribute('data-blackboard-surface', 'derived');
    expect(derivedBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
    expect(await screen.findByText('blackboard.planRunEmpty')).toBeInTheDocument();
  });

  it('renders durable plan snapshot state', async () => {
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValueOnce({
      workspace_id: 'ws-1',
      plan: {
        id: 'plan-1',
        workspace_id: 'ws-1',
        goal_id: 'goal-1',
        status: 'active',
        created_at: '2026-04-23T00:00:00Z',
        nodes: [
          {
            id: 'node-task-1',
            parent_id: 'goal-1',
            kind: 'task',
            title: 'Ship autonomous plan',
            description: '',
            depends_on: [],
            acceptance_criteria: [],
            recommended_capabilities: [],
            intent: 'in_progress',
            execution: 'dispatched',
            progress: {
              percent: 25,
              confidence: 0.8,
              note: '',
            },
            assignee_agent_id: 'agent-1',
            current_attempt_id: 'attempt-1',
            workspace_task_id: null,
            priority: 1,
            metadata: {},
            created_at: '2026-04-23T00:00:00Z',
          },
        ],
        counts: {
          'intent:in_progress': 1,
        },
      },
      blackboard: [
        {
          plan_id: 'plan-1',
          key: 'artifact.spec',
          value: { ok: true },
          published_by: 'planner',
          version: 2,
          metadata: {},
        },
      ],
      outbox: [
        {
          id: 'outbox-1',
          plan_id: 'plan-1',
          workspace_id: 'ws-1',
          event_type: 'supervisor_tick',
          status: 'completed',
          attempt_count: 1,
          max_attempts: 3,
          metadata: {},
          created_at: '2026-04-23T00:00:00Z',
        },
      ],
      events: [
        {
          id: 'event-1',
          plan_id: 'plan-1',
          workspace_id: 'ws-1',
          node_id: 'node-task-1',
          attempt_id: 'attempt-1',
          event_type: 'verification_completed',
          source: 'workspace_plan_verifier',
          actor_id: null,
          payload: { summary: 'verified' },
          created_at: '2026-04-23T00:00:00Z',
        },
      ],
    });

    render(
      <StatusTab
        stats={{
          completionRatio: 0,
          discussions: 0,
          activeAgents: 0,
          pendingAdjudicationTasks: 0,
        }}
        topologyEdges={[]}
        agents={[]}
        tasks={[]}
        workspaceId="ws-1"
        statusBadgeTone={() => 'bg-green-500'}
      />
    );

    expect(await screen.findByText('Ship autonomous plan')).toBeInTheDocument();
    expect(screen.getByText('artifact.spec')).toBeInTheDocument();
    expect(screen.getByText('supervisor_tick')).toBeInTheDocument();
    expect(screen.getByText('verification_completed')).toBeInTheDocument();
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 8,
      eventLimit: 8,
    });
  });
});
