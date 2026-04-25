import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StatusTab } from '@/components/blackboard/tabs/StatusTab';
import { workspaceAutonomyService, workspacePlanService } from '@/services/workspaceService';
import { fireEvent, render, screen, waitFor } from '@/test/utils';

vi.mock('@/services/workspaceService', () => ({
  workspaceAutonomyService: {
    tick: vi.fn(),
  },
  workspacePlanService: {
    getSnapshot: vi.fn(),
    reopenBlockedNode: vi.fn(),
    requestNodeReplan: vi.fn(),
    retryOutboxItem: vi.fn(),
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
    vi.mocked(workspaceAutonomyService.tick).mockResolvedValue({
      triggered: false,
      root_task_id: null,
      reason: 'no_root_needs_progress',
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
            actions: {
              request_replan: {
                enabled: true,
                label: 'Request replan',
                requires_confirmation: true,
              },
              reopen_blocked: {
                enabled: false,
                label: 'Reopen blocked node',
                reason: 'Only blocked nodes can be reopened.',
                requires_confirmation: false,
              },
            },
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
          payload: { node_id: 'node-task-1' },
          status: 'completed',
          attempt_count: 1,
          max_attempts: 3,
          metadata: {},
          created_at: '2026-04-23T00:00:00Z',
          actions: {
            retry_outbox: {
              enabled: false,
              label: 'Retry now',
              reason: 'Only failed or dead-letter jobs can be retried.',
              requires_confirmation: false,
            },
          },
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
          payload: { passed: true, summary: 'verified' },
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

    expect((await screen.findAllByText('Ship autonomous plan'))[0]).toBeInTheDocument();
    expect(screen.getByText('artifact.spec')).toBeInTheDocument();
    expect(screen.getByText('supervisor_tick')).toBeInTheDocument();
    expect(screen.getAllByText('Verifier accepted')[0]).toBeInTheDocument();
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 20,
      eventLimit: 80,
    });
  });

  it('refreshes durable plan snapshot when workspace plan events arrive', async () => {
    const { rerender } = render(
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
        planRefreshToken={0}
      />
    );

    await waitFor(() => {
      expect(workspacePlanService.getSnapshot).toHaveBeenCalledTimes(1);
    });

    rerender(
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
        planRefreshToken={1}
      />
    );

    await waitFor(() => {
      expect(workspacePlanService.getSnapshot).toHaveBeenCalledTimes(2);
    });
  });

  it('triggers workspace autonomy from the durable plan header', async () => {
    vi.mocked(workspaceAutonomyService.tick)
      .mockResolvedValueOnce({
        triggered: true,
        root_task_id: 'root-1',
        reason: 'triggered',
      })
      .mockResolvedValueOnce({
        triggered: false,
        root_task_id: 'root-1',
        reason: 'cooling_down',
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

    expect(await screen.findByText('blackboard.planRunEmpty')).toBeInTheDocument();

    fireEvent.click(screen.getByText('blackboard.planRunRunAutonomy'));
    await waitFor(() => {
      expect(workspaceAutonomyService.tick).toHaveBeenCalledWith('ws-1', { force: false });
    });
    expect(await screen.findByText('blackboard.planRunAutonomyTriggered')).toBeInTheDocument();

    fireEvent.click(screen.getByText('blackboard.planRunForceAutonomy'));
    await waitFor(() => {
      expect(workspaceAutonomyService.tick).toHaveBeenCalledWith('ws-1', { force: true });
    });
  });

  it('filters the durable workbench and invokes recovery actions', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValue({
      workspace_id: 'ws-1',
      plan: {
        id: 'plan-1',
        workspace_id: 'ws-1',
        goal_id: 'goal-1',
        status: 'active',
        created_at: '2026-04-23T00:00:00Z',
        nodes: [
          {
            id: 'node-blocked-1',
            parent_id: 'goal-1',
            kind: 'task',
            title: 'Blocked implementation',
            description: 'Waiting on operator recovery',
            depends_on: [],
            acceptance_criteria: [],
            recommended_capabilities: [],
            intent: 'blocked',
            execution: 'reported',
            progress: { percent: 45, confidence: 0.6, note: '' },
            assignee_agent_id: 'agent-1',
            current_attempt_id: 'attempt-1',
            workspace_task_id: 'task-1',
            priority: 1,
            metadata: {},
            created_at: '2026-04-23T00:00:00Z',
            actions: {
              open_attempt: {
                enabled: true,
                label: 'Open attempt',
                requires_confirmation: false,
              },
              request_replan: {
                enabled: true,
                label: 'Request replan',
                requires_confirmation: true,
              },
              reopen_blocked: {
                enabled: true,
                label: 'Reopen blocked node',
                requires_confirmation: false,
              },
            },
          },
        ],
        counts: { 'intent:blocked': 1 },
      },
      blackboard: [
        {
          plan_id: 'plan-1',
          key: 'artifact.blocked-report',
          value: { summary: 'blocked evidence' },
          published_by: 'verifier',
          version: 1,
          metadata: {},
        },
      ],
      outbox: [
        {
          id: 'outbox-failed-1',
          plan_id: 'plan-1',
          workspace_id: 'ws-1',
          event_type: 'supervisor_tick',
          payload: { node_id: 'node-blocked-1' },
          status: 'failed',
          attempt_count: 2,
          max_attempts: 3,
          last_error: 'lease expired',
          metadata: {},
          created_at: '2026-04-23T00:00:00Z',
          actions: {
            retry_outbox: {
              enabled: true,
              label: 'Retry now',
              requires_confirmation: false,
            },
          },
        },
      ],
      events: [
        {
          id: 'event-1',
          plan_id: 'plan-1',
          workspace_id: 'ws-1',
          node_id: 'node-blocked-1',
          attempt_id: 'attempt-1',
          event_type: 'worker_report_terminal',
          source: 'worker',
          actor_id: 'agent-1',
          payload: { summary: 'needs intervention' },
          created_at: '2026-04-23T00:00:00Z',
        },
      ],
    });
    vi.mocked(workspacePlanService.retryOutboxItem).mockResolvedValue({
      ok: true,
      message: 'Outbox job queued for retry.',
      plan_id: 'plan-1',
      outbox_id: 'outbox-failed-1',
    });
    vi.mocked(workspacePlanService.reopenBlockedNode).mockResolvedValue({
      ok: true,
      message: 'Blocked plan node reopened.',
      plan_id: 'plan-1',
      node_id: 'node-blocked-1',
    });
    vi.mocked(workspacePlanService.requestNodeReplan).mockResolvedValue({
      ok: true,
      message: 'Plan node sent back for supervisor recovery.',
      plan_id: 'plan-1',
      node_id: 'node-blocked-1',
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
        tasks={[
          {
            id: 'task-1',
            workspace_id: 'ws-1',
            title: 'Blocked implementation',
            status: 'blocked',
            current_attempt_id: 'attempt-1',
            current_attempt_conversation_id: 'conv-1',
            created_at: '2026-04-23T00:00:00Z',
            metadata: {},
          },
        ]}
        workspaceId="ws-1"
        tenantId="tenant-1"
        projectId="project-1"
        statusBadgeTone={() => 'bg-green-500'}
      />
    );

    expect(await screen.findAllByText('Blocked implementation')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('blackboard.planRunSearch'), {
      target: { value: 'blocked' },
    });
    expect(screen.getByText('artifact.blocked-report')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open attempt' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agent-workspace/conv-1?projectId=project-1&workspaceId=ws-1'
    );

    fireEvent.change(screen.getByLabelText('blackboard.planRunOperatorReason'), {
      target: { value: 'operator reviewed blocked evidence' },
    });

    fireEvent.click(screen.getByText('Retry now'));
    await waitFor(() => {
      expect(workspacePlanService.retryOutboxItem).toHaveBeenCalledWith('ws-1', 'outbox-failed-1', {
        reason: 'operator reviewed blocked evidence',
      });
    });

    fireEvent.click(screen.getByText('Reopen blocked node'));
    await waitFor(() => {
      expect(workspacePlanService.reopenBlockedNode).toHaveBeenCalledWith(
        'ws-1',
        'node-blocked-1',
        {
          reason: 'operator reviewed blocked evidence',
        }
      );
    });

    fireEvent.click(screen.getByText('Request replan'));
    await waitFor(() => {
      expect(workspacePlanService.requestNodeReplan).toHaveBeenCalledWith(
        'ws-1',
        'node-blocked-1',
        {
          reason: 'operator reviewed blocked evidence',
        }
      );
    });
  });
});
