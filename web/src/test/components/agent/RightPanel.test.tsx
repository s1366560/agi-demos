/**
 * TDD Tests for RightPanel refactored components
 *
 * Test coverage for:
 * - RightPanel (uses the shared Resizer component, tested in Resizer.test.tsx)
 */

import type { ReactElement } from 'react';

import { MemoryRouter } from 'react-router-dom';

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock antd components completely to avoid complex dependencies
vi.mock('antd', () => ({
  Tabs: ({ _children, activeKey, onChange, items }: any) => (
    <div data-testid="tabs">
      {items?.map((item: any) => (
        <button key={item.key} data-testid={`tab-${item.key}`} onClick={() => onChange?.(item.key)}>
          {typeof item.label === 'string' ? item.label : 'Tab'}
        </button>
      ))}
      <div data-testid="tabs-content">{items?.find((i: any) => i.key === activeKey)?.children}</div>
    </div>
  ),
  Button: ({ children, onClick, icon, ...props }: any) => (
    <button onClick={onClick} data-testid="close-button" {...props}>
      {icon}
      {children}
    </button>
  ),
  Badge: ({ children }: any) => <span>{children}</span>,
  Empty: ({ description }: any) => <div>{description}</div>,
  Alert: ({ message, description }: any) => (
    <div data-testid="alert">
      <strong>{message}</strong>
      <p>{description}</p>
    </div>
  ),
  Spin: () => <div data-testid="spin">Loading...</div>,
}));

vi.mock('@/stores/sandbox', () => ({
  useSandboxStore: vi.fn(() => ({
    activeSandboxId: null,
    toolExecutions: [],
    currentTool: null,
  })),
}));

vi.mock('@/services/agent/graph/agentGraphApi', () => ({
  agentGraphApi: {
    getGraph: vi.fn(),
  },
}));

vi.mock('@/services/workspaceService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/workspaceService')>();
  return {
    ...actual,
    workspaceTaskService: {
      ...actual.workspaceTaskService,
      list: vi.fn(),
    },
    workspacePlanService: {
      ...actual.workspacePlanService,
      getSnapshot: vi.fn(),
    },
  };
});

// Mock SandboxSection to avoid complex dependencies
vi.mock('@/components/agent/SandboxSection', () => ({
  SandboxSection: ({ sandboxId, toolExecutions, currentTool }: any) => (
    <div data-testid="sandbox-section" data-sandbox-id={sandboxId || ''}>
      <div data-testid="tool-executions-count">{toolExecutions?.length || 0}</div>
      {currentTool && <div data-testid="current-tool">{currentTool.name}</div>}
      <div>Sandbox Section Mock</div>
    </div>
  ),
}));

// Import components after mocking
// eslint-disable-next-line no-restricted-imports
import { agentGraphApi } from '@/services/agent/graph/agentGraphApi';
// eslint-disable-next-line no-restricted-imports
import { workspacePlanService, workspaceTaskService } from '@/services/workspaceService';
// eslint-disable-next-line no-restricted-imports
import { useGraphStore } from '@/stores/graphStore';
// eslint-disable-next-line no-restricted-imports
import { useWorkspaceStore } from '@/stores/workspace';
// eslint-disable-next-line no-restricted-imports
import { RightPanel } from '@/components/agent/RightPanel';

function renderRightPanel(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function mockWorkspaceSnapshot() {
  return {
    workspace_id: 'ws-1',
    plan: {
      id: 'plan-1',
      workspace_id: 'ws-1',
      goal_id: 'goal-1',
      status: 'active',
      created_at: '2026-05-01T00:00:00Z',
      counts: {},
      nodes: [
        {
          id: 'goal-1',
          parent_id: null,
          kind: 'goal',
          title: 'Complete workspace delivery',
          description: '',
          depends_on: [],
          acceptance_criteria: [],
          recommended_capabilities: [],
          intent: 'todo',
          execution: 'pending',
          progress: { percent: 0, confidence: 0.8, note: '' },
          assignee_agent_id: null,
          current_attempt_id: null,
          workspace_task_id: null,
          priority: 0,
          metadata: {},
          created_at: '2026-05-01T00:00:00Z',
        },
        {
          id: 'task-1',
          parent_id: 'goal-1',
          kind: 'task',
          title: 'Workspace deploy task',
          description: 'Deploy through Drone.',
          depends_on: [],
          acceptance_criteria: [],
          recommended_capabilities: [],
          intent: 'done',
          execution: 'completed',
          progress: { percent: 100, confidence: 0.8, note: '' },
          assignee_agent_id: null,
          current_attempt_id: 'attempt-1',
          workspace_task_id: 'workspace-task-1',
          priority: 1,
          metadata: { iteration_index: 1 },
          created_at: '2026-05-01T00:00:00Z',
        },
      ],
    },
    iteration: {
      current_iteration: 1,
      loop_label: 'Iteration loop',
      cadence: 'manual',
      loop_status: 'active',
      max_iterations: 3,
      completed_iterations: [],
      current_sprint_goal: 'Ship workspace delivery',
      review_summary: '',
      stop_reason: '',
      active_phase: 'execute',
      active_phase_label: 'Execute',
      next_action: '',
      task_count: 1,
      task_budget: 1,
      phases: [],
      deliverables: [],
      feedback_items: [],
      history: [],
      actions: {},
    },
    blackboard: [],
    outbox: [],
    events: [],
    root_goal: {
      id: 'goal-1',
      workspace_id: 'ws-1',
      title: 'Complete workspace delivery',
      status: 'done',
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z',
    },
  };
}

describe('RightPanel (Refactored)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useGraphStore.getState().clearAll();
    useWorkspaceStore.setState({ planRefreshCounters: {} });
    vi.mocked(workspaceTaskService.list).mockResolvedValue([]);
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValue(mockWorkspaceSnapshot() as any);
    vi.mocked(agentGraphApi.getGraph).mockResolvedValue({
      id: 'graph-1',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      name: 'Execution graph',
      description: '',
      pattern: 'pipeline',
      nodes: [
        {
          node_id: 'planner',
          agent_definition_id: 'planner-agent',
          label: 'Planner',
          instruction: '',
          config: {},
          is_entry: true,
          is_terminal: false,
        },
      ],
      edges: [],
      shared_context_keys: [],
      max_total_steps: 10,
      metadata: {},
      is_active: true,
      created_at: '2026-05-01T00:00:00Z',
    });
  });

  it('should not render when collapsed', () => {
    const { container } = renderRightPanel(<RightPanel collapsed={true} />);

    expect(container.firstChild).toBe(null);
  });

  // Note: Full integration tests for RightPanel are skipped due to antd Tabs complexity
  // RightPanel composes separately tested components (Resizer, plan/task panels)

  it('should be defined and exportable', () => {
    expect(RightPanel).toBeDefined();
  });

  it('should have displayName for debugging', () => {
    expect(RightPanel.displayName).toBe('RightPanel');
  });

  it('should render execution insights when provided', () => {
    renderRightPanel(
      <RightPanel
        tasks={[]}
        executionPathDecision={{
          route_id: 'route_1',
          trace_id: 'trace_1',
          path: 'react_loop',
          confidence: 0.8,
          reason: 'default route',
          metadata: { domain_lane: 'general' },
        }}
        selectionTrace={{
          route_id: 'route_1',
          initial_count: 12,
          final_count: 6,
          removed_total: 6,
          tool_budget: 8,
          stages: [],
        }}
        policyFiltered={{
          route_id: 'route_1',
          trace_id: 'trace_1',
          removed_total: 4,
          stage_count: 2,
          budget_exceeded_stages: ['semantic_ranker_stage'],
        }}
      />
    );

    expect(screen.getByTestId('execution-insights')).toBeInTheDocument();
    expect(screen.getByText('Execution Insights')).toBeInTheDocument();
    expect(screen.getByText(/Path:/)).toBeInTheDocument();
    expect(screen.getByText(/trace_id:/)).toBeInTheDocument();
    expect(screen.getByText(/tool_budget:/)).toBeInTheDocument();
    expect(screen.getByText(/budget_exceeded:/)).toBeInTheDocument();
  });

  it('should render execution narrative and toolset diagnostics', () => {
    renderRightPanel(
      <RightPanel
        tasks={[]}
        executionNarrative={[
          {
            id: 'narrative-1',
            stage: 'routing',
            summary: '[Routing] react_loop (0.82) - default route',
            timestamp: Date.now(),
          },
        ]}
        latestToolsetChange={{
          source: 'plugin_manager',
          action: 'reload',
          plugin_name: 'demo-plugin',
          trace_id: 'toolset-trace-1',
          refresh_status: 'success',
          refreshed_tool_count: 18,
        }}
      />
    );

    expect(screen.getByTestId('execution-narrative')).toBeInTheDocument();
    expect(screen.getByText('Execution Narrative')).toBeInTheDocument();
    expect(screen.getByText(/demo-plugin/)).toBeInTheDocument();
    expect(screen.getByText(/refresh: success/)).toBeInTheDocument();
  });

  it('should disable graph tab when no graph run is active', () => {
    renderRightPanel(<RightPanel tasks={[]} />);

    expect(screen.getByText('Graph').closest('button')).toBeDisabled();
  });

  it('should render current workspace tasks and plan nodes in the task panel', async () => {
    vi.mocked(workspaceTaskService.list).mockResolvedValueOnce([]);

    renderRightPanel(
      <RightPanel
        tasks={[]}
        conversationId="conv-1"
        workspaceId="ws-1"
        currentWorkspaceTaskId="workspace-task-1"
      />
    );

    expect(await screen.findByText('Workspace deploy task')).toBeInTheDocument();
    expect(screen.getByText('1 item')).toBeInTheDocument();
    expect(screen.getByText('2/2 plan nodes done')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-task-plan-row-task-1')).toHaveAttribute(
      'data-current-workspace-task',
      'true'
    );
    expect(workspaceTaskService.list).toHaveBeenCalledWith('ws-1');
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 0,
      eventLimit: 0,
      includeDetails: false,
      recoverStaleAttempts: false,
    });
  });

  it('should render workspace execution graph when the current conversation is workspace-active', async () => {
    useGraphStore
      .getState()
      .runStarted('run-other', 'graph-1', 'Stale graph', 'pipeline', ['planner'], 'other-conv');

    renderRightPanel(
      <RightPanel
        tasks={[]}
        conversationId="conv-1"
        workspaceId="ws-1"
        currentWorkspaceTaskId="workspace-task-1"
      />
    );

    expect(screen.getByText('Graph').closest('button')).not.toBeDisabled();
    fireEvent.click(screen.getByText('Graph'));
    expect(await screen.findByTestId('execution-dag-graph')).toBeInTheDocument();
    expect(screen.getAllByText('Workspace deploy task').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('execution-dag-node-task-1')).toHaveAttribute(
      'data-current-session-node',
      'true'
    );
    expect(workspacePlanService.getSnapshot).toHaveBeenCalledWith('ws-1', {
      outboxLimit: 0,
      eventLimit: 0,
      includeDetails: false,
      recoverStaleAttempts: false,
    });
    expect(agentGraphApi.getGraph).not.toHaveBeenCalled();
  });

  it('should keep the workspace execution graph mounted during background refresh', async () => {
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValueOnce(
      mockWorkspaceSnapshot() as any
    );

    renderRightPanel(
      <RightPanel
        tasks={[]}
        conversationId="conv-1"
        workspaceId="ws-1"
        currentWorkspaceTaskId="workspace-task-1"
      />
    );

    fireEvent.click(screen.getByText('Graph'));
    expect(await screen.findByTestId('execution-dag-graph')).toBeInTheDocument();

    vi.mocked(workspacePlanService.getSnapshot).mockImplementationOnce(
      () => new Promise(() => undefined)
    );

    act(() => {
      useWorkspaceStore.setState({ planRefreshCounters: { 'ws-1': 1 } });
    });

    const refreshIndicator = await screen.findByTestId('workspace-graph-refreshing');
    expect(refreshIndicator).toHaveClass('absolute');
    expect(refreshIndicator).toHaveClass('h-2');
    expect(refreshIndicator).toHaveClass('w-2');
    expect(screen.getByTestId('execution-dag-graph')).toBeInTheDocument();
    expect(screen.queryByText('Loading workspace graph')).not.toBeInTheDocument();
  });

  it('should keep the latest workspace execution graph when refresh fails', async () => {
    vi.mocked(workspacePlanService.getSnapshot).mockResolvedValueOnce(
      mockWorkspaceSnapshot() as any
    );

    renderRightPanel(
      <RightPanel
        tasks={[]}
        conversationId="conv-1"
        workspaceId="ws-1"
        currentWorkspaceTaskId="workspace-task-1"
      />
    );

    fireEvent.click(screen.getByText('Graph'));
    expect(await screen.findByTestId('execution-dag-graph')).toBeInTheDocument();

    vi.mocked(workspacePlanService.getSnapshot).mockRejectedValueOnce(new Error('network blip'));

    act(() => {
      useWorkspaceStore.setState({ planRefreshCounters: { 'ws-1': 1 } });
    });

    expect(
      await screen.findByText('Showing the latest available workspace graph.')
    ).toBeInTheDocument();
    expect(screen.getByTestId('execution-dag-graph')).toBeInTheDocument();
  });

  it('should ignore graph runs from a different conversation', () => {
    useGraphStore
      .getState()
      .runStarted('run-other', 'graph-1', 'Other graph', 'pipeline', ['planner'], 'other-conv');

    renderRightPanel(<RightPanel tasks={[]} conversationId="conv-1" />);

    expect(screen.getByText('Graph').closest('button')).toBeDisabled();
  });

  it('should render graph tab when a graph run is active', async () => {
    useGraphStore
      .getState()
      .runStarted('run-1', 'graph-1', 'Execution graph', 'pipeline', ['planner'], 'conv-1');
    useGraphStore
      .getState()
      .nodeStarted('run-1', 'planner', 'Planner', 'planner-agent', 'session-1');

    renderRightPanel(<RightPanel tasks={[]} conversationId="conv-1" />);

    expect(await screen.findByTestId('execution-dag-graph')).toBeInTheDocument();
    expect(screen.getByText('Planner')).toBeInTheDocument();
    expect(agentGraphApi.getGraph).toHaveBeenCalledWith('graph-1');
  });
});
