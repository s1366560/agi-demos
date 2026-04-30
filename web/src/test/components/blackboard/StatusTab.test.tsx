import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StatusTab } from '@/components/blackboard/tabs/StatusTab';
import {
  workspaceAutonomyService,
  workspaceBlackboardService,
  workspacePlanService,
} from '@/services/workspaceService';
import { fireEvent, render, screen, waitFor } from '@/test/utils';

vi.mock('@/services/workspaceService', () => ({
  workspaceBlackboardService: {
    getExecutionDiagnostics: vi.fn(),
  },
  workspaceAutonomyService: {
    tick: vi.fn(),
  },
  workspacePlanService: {
    getSnapshot: vi.fn(),
    pauseAutoLoop: vi.fn(),
    regenerateDeliveryContract: vi.fn(),
    reopenBlockedNode: vi.fn(),
    requestPipelineRun: vi.fn(),
    requestNodeReplan: vi.fn(),
    resumeAutoLoop: vi.fn(),
    retryOutboxItem: vi.fn(),
    triggerNextIteration: vi.fn(),
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
    vi.mocked(workspaceBlackboardService.getExecutionDiagnostics).mockResolvedValue({
      workspace_id: 'ws-1',
      generated_at: '2026-04-27T00:00:00Z',
      task_status_counts: {},
      attempt_status_counts: {},
      tool_status_counts: {},
      tasks: [],
      blockers: [],
      pending_adjudications: [],
      evidence_gaps: [],
      recent_tool_failures: [],
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

  it('renders execution diagnostics signals from the blackboard API', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(workspaceBlackboardService.getExecutionDiagnostics).mockResolvedValueOnce({
      workspace_id: 'ws-1',
      generated_at: '2026-04-27T00:00:00Z',
      task_status_counts: { blocked: 1 },
      attempt_status_counts: { blocked: 1 },
      tool_status_counts: { failed: 1 },
      tasks: [],
      blockers: [
        {
          type: 'task_blocked',
          task_id: 'task-1',
          title: 'Implement worker tracking',
          reason: 'Task is blocked',
        },
        {
          type: 'attempt_blocked',
          task_id: 'task-1',
          attempt_id: 'attempt-1',
          title: 'Implement worker tracking',
          reason: 'Worker reported a blocking dependency',
        },
      ],
      pending_adjudications: [],
      evidence_gaps: [
        {
          task_id: 'task-2',
          title: 'Verify deployment plan',
          reason: 'No verification evidence or successful tool execution recorded',
        },
      ],
      recent_tool_failures: [
        {
          task_id: 'task-3',
          title: 'Run diagnostics',
          tool_execution_id: 'ter-1',
          tool_name: 'bash',
          error: 'command failed',
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
        tenantId="tenant-1"
        projectId="project-1"
        statusBadgeTone={() => 'bg-green-500'}
      />
    );

    await waitFor(() => {
      expect(workspaceBlackboardService.getExecutionDiagnostics).toHaveBeenCalledWith(
        'tenant-1',
        'project-1',
        'ws-1'
      );
    });
    expect(await screen.findAllByText('Implement worker tracking')).toHaveLength(2);
    expect(screen.getByText('Verify deployment plan')).toBeInTheDocument();
    expect(screen.getByText('bash')).toBeInTheDocument();
    expect(screen.getByText('command failed')).toBeInTheDocument();
    expect(consoleError.mock.calls.some((call) => call.join(' ').includes('same key'))).toBe(false);
    consoleError.mockRestore();
  });

  it('renders durable plan snapshot state', async () => {
    vi.mocked(workspacePlanService.pauseAutoLoop).mockResolvedValue({
      ok: true,
      message: 'Automatic iteration loop paused.',
      plan_id: 'plan-1',
      node_id: 'goal-1',
    });
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
            phase_contract: {
              phase: 'implement',
              title: 'Implement',
              entry_gate: 'Story card and write scope are bounded.',
              exit_gate: 'Changed files and a local recovery boundary are recorded.',
              required_evidence: ['changed files', 'commit or recovery ref'],
              allowed_routing: ['continue', 'recover', 'replan'],
              blocked_semantics: 'Blocked is reserved for human-only inputs.',
            },
            evidence_bundle: {
              artifacts: ['artifact.spec'],
              evidence_refs: ['pipeline_run:success:run-1'],
              changed_files: ['web/src/App.tsx'],
              pipeline_refs: ['pipeline_run:success:run-1'],
              verification_summary: 'verified',
              review_summary: 'Review requested implementation evidence.',
            },
            gate_status: {
              status: 'running',
              summary: 'This phase is collecting its required evidence.',
              missing: ['commit or recovery ref'],
              evidence_refs: ['pipeline_run:success:run-1'],
              routing: 'continue',
            },
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
      iteration: {
        current_iteration: 1,
        loop_label: 'Scrum feedback loop',
        cadence: 'research -> plan -> implement -> test -> deploy -> review',
        loop_status: 'active',
        max_iterations: 8,
        completed_iterations: [],
        current_sprint_goal: 'Ship the autonomous plan increment.',
        review_summary: 'Review requested implementation evidence.',
        stop_reason: '',
        active_phase: 'implement',
        active_phase_label: 'Implement',
        next_action: 'Let active implement work finish and collect verification evidence.',
        task_count: 1,
        task_budget: 6,
        phases: [
          {
            id: 'research',
            label: 'Research',
            total: 0,
            done: 0,
            running: 0,
            blocked: 0,
            progress: 0,
          },
          { id: 'plan', label: 'Plan', total: 0, done: 0, running: 0, blocked: 0, progress: 0 },
          {
            id: 'implement',
            label: 'Implement',
            total: 1,
            done: 0,
            running: 1,
            blocked: 0,
            progress: 25,
            gate_status: {
              status: 'running',
              summary: 'Implement evidence is being collected.',
              missing: ['commit or recovery ref'],
              evidence_refs: ['pipeline_run:success:run-1'],
              routing: 'continue',
            },
            required_artifacts: ['changed files', 'commit or recovery ref'],
            missing_artifacts: ['commit or recovery ref'],
            summary: 'Implement evidence is being collected.',
          },
          { id: 'test', label: 'Test', total: 0, done: 0, running: 0, blocked: 0, progress: 0 },
          { id: 'deploy', label: 'Deploy', total: 0, done: 0, running: 0, blocked: 0, progress: 0 },
          { id: 'review', label: 'Review', total: 0, done: 0, running: 0, blocked: 0, progress: 0 },
        ],
        deliverables: ['artifact.spec'],
        feedback_items: ['Add browser verification before completing the goal.'],
        history: [
          {
            iteration_index: 1,
            verdict: 'continue_next_iteration',
            summary: 'Review requested implementation evidence.',
            confidence: 0.82,
            next_sprint_goal: 'Ship the autonomous plan increment.',
            created_at: '2026-04-29T00:00:00Z',
          },
        ],
        actions: {
          pause_auto_loop: {
            enabled: true,
            label: 'Pause auto-loop',
            requires_confirmation: false,
          },
          resume_auto_loop: {
            enabled: false,
            label: 'Resume auto-loop',
            reason: 'Only paused or suspended loops can be resumed.',
            requires_confirmation: false,
          },
          trigger_next_iteration: {
            enabled: true,
            label: 'Plan next iteration',
            requires_confirmation: false,
          },
        },
      },
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
    expect(screen.getAllByText('artifact.spec').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Iteration 1').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('active').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Ship the autonomous plan increment.').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Review requested implementation evidence.').length).toBeGreaterThan(
      0
    );
    expect(screen.getAllByText('Implement')[0]).toBeInTheDocument();
    expect(
      screen.getByText('Let active implement work finish and collect verification evidence.')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Add browser verification before completing the goal.')
    ).toBeInTheDocument();
    expect(screen.getByText('Review history')).toBeInTheDocument();
    expect(screen.getByText('Plan next')).toBeInTheDocument();
    expect(screen.getByText('Phase contract')).toBeInTheDocument();
    expect(screen.getAllByText(/commit or recovery ref/).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
    expect(screen.getAllByText('artifact.spec').length).toBeGreaterThanOrEqual(2);
    fireEvent.click(screen.getByRole('button', { name: 'Runs' }));
    expect(screen.getByText('supervisor_tick')).toBeInTheDocument();
    expect(screen.getAllByText('Verifier accepted')[0]).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    expect(screen.getByText('Review gate')).toBeInTheDocument();
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 20,
      eventLimit: 80,
    });

    fireEvent.click(screen.getByText('Pause'));
    await waitFor(() => {
      expect(workspacePlanService.pauseAutoLoop).toHaveBeenCalledWith('ws-1', {
        reason: 'operator action from central blackboard',
      });
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
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    expect(screen.getByText('artifact.blocked-report')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open attempt' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agent-workspace/conv-1?projectId=project-1&workspaceId=ws-1'
    );

    fireEvent.change(screen.getByLabelText('blackboard.planRunOperatorReason'), {
      target: { value: 'operator reviewed blocked evidence' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Runs' }));
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
