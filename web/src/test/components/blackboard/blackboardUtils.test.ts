import { describe, expect, it } from 'vitest';

import {
  buildBlackboardTaskBoardTasks,
  buildBlackboardNotes,
  buildBlackboardStats,
  buildCanvasActors,
  calculateWorkspacePlanCompletionRatio,
  calculateWorkspaceTaskCompletionRatio,
  groupTasksByStatus,
} from '@/components/blackboard/blackboardUtils';

import type {
  BlackboardPost,
  CyberObjective,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
  WorkspacePlan,
  WorkspacePlanRootGoal,
  WorkspaceTask,
} from '@/types/workspace';

const BASE_POST: BlackboardPost = {
  id: 'post-1',
  workspace_id: 'ws-1',
  author_id: 'user-1',
  title: 'Pinned discussion',
  content: 'Summarize the latest release learnings for everyone.',
  status: 'open',
  is_pinned: true,
  metadata: {},
  created_at: '2026-03-30T08:00:00Z',
};

const BASE_TASK: WorkspaceTask = {
  id: 'task-1',
  workspace_id: 'ws-1',
  title: 'Ship board redesign',
  status: 'todo',
  metadata: {},
  created_at: '2026-03-30T08:00:00Z',
};

describe('blackboardUtils', () => {
  it('groups tasks by status and sorts higher priority items first', () => {
    const tasks: WorkspaceTask[] = [
      {
        ...BASE_TASK,
        id: 'task-low',
        title: 'Low',
        priority: 'P4',
        created_at: '2026-03-30T09:00:00Z',
      },
      {
        ...BASE_TASK,
        id: 'task-high',
        title: 'High',
        priority: 'P1',
        created_at: '2026-03-30T08:30:00Z',
      },
      {
        ...BASE_TASK,
        id: 'task-done',
        title: 'Done',
        status: 'done',
        created_at: '2026-03-30T07:00:00Z',
      },
    ];

    const grouped = groupTasksByStatus(tasks);

    expect(grouped.todo.map((task) => task.id)).toEqual(['task-high', 'task-low']);
    expect(grouped.done.map((task) => task.id)).toEqual(['task-done']);
    expect(grouped.blocked).toHaveLength(0);
  });

  it('derives blackboard stats from tasks, posts, agents, and seats', () => {
    const agents: WorkspaceAgent[] = [
      {
        id: 'agent-1',
        workspace_id: 'ws-1',
        agent_id: 'agent-alpha',
        is_active: true,
        created_at: '2026-03-30T08:00:00Z',
      },
      {
        id: 'agent-2',
        workspace_id: 'ws-1',
        agent_id: 'agent-beta',
        is_active: false,
        status: 'busy',
        created_at: '2026-03-30T08:00:00Z',
      },
    ];
    const topologyNodes: TopologyNode[] = [
      {
        id: 'human-1',
        workspace_id: 'ws-1',
        node_type: 'human_seat',
        title: 'Admin',
        position_x: 0,
        position_y: 0,
        data: {},
      },
    ];
    const stats = buildBlackboardStats(
      [
        { ...BASE_TASK, id: 'todo-task', status: 'todo' },
        { ...BASE_TASK, id: 'done-task', status: 'done' },
        { ...BASE_TASK, id: 'blocked-task', status: 'blocked' },
      ],
      [BASE_POST, { ...BASE_POST, id: 'post-2', is_pinned: false, status: 'archived' }],
      agents,
      topologyNodes
    );

    expect(stats.totalTasks).toBe(3);
    expect(stats.todoTasks).toBe(1);
    expect(stats.inProgressTasks).toBe(0);
    expect(stats.completedTasks).toBe(1);
    expect(stats.blockedTasks).toBe(1);
    expect(stats.pendingAdjudicationTasks).toBe(0);
    expect(stats.activeAgents).toBe(2);
    expect(stats.humanSeats).toBe(1);
    expect(stats.discussions).toBe(2);
    expect(stats.pinnedPosts).toBe(1);
    expect(stats.completionRatio).toBe(33);
  });

  it('counts pending leader adjudication tasks', () => {
    const stats = buildBlackboardStats(
      [
        {
          ...BASE_TASK,
          id: 'pending-task',
          status: 'in_progress',
          metadata: {
            pending_leader_adjudication: true,
          },
        },
      ],
      [],
      [],
      []
    );

    expect(stats.pendingAdjudicationTasks).toBe(1);
  });

  it('uses direct workspace task counts instead of durable plan intent projections', () => {
    const tasks: WorkspaceTask[] = [
      { ...BASE_TASK, id: 'done-task', status: 'done' },
      { ...BASE_TASK, id: 'stale-running-1', status: 'in_progress' },
      { ...BASE_TASK, id: 'stale-running-2', status: 'in_progress' },
    ];
    const stats = buildBlackboardStats(tasks, [], [], []);

    expect(stats.totalTasks).toBe(3);
    expect(stats.completedTasks).toBe(1);
    expect(stats.todoTasks).toBe(0);
    expect(stats.inProgressTasks).toBe(2);
    expect(stats.completionRatio).toBe(33);
    expect(calculateWorkspaceTaskCompletionRatio(tasks)).toBe(stats.completionRatio);
  });

  it('uses current plan nodes before workspace-wide historical tasks when a plan is provided', () => {
    const tasks: WorkspaceTask[] = [
      { ...BASE_TASK, id: 'old-done-task', status: 'done' },
      { ...BASE_TASK, id: 'stale-running-task', status: 'in_progress' },
      { ...BASE_TASK, id: 'extra-root-task', status: 'in_progress' },
    ];
    const plan: WorkspacePlan = {
      id: 'plan-current',
      workspace_id: 'ws-1',
      goal_id: 'goal-current',
      status: 'active',
      created_at: '2026-03-30T08:00:00Z',
      nodes: Array.from({ length: 52 }, (_, index) => ({
        id: `node-${String(index)}`,
        parent_id: null,
        kind: 'task',
        title: `Task ${String(index)}`,
        description: '',
        depends_on: [],
        acceptance_criteria: [],
        recommended_capabilities: [],
        intent: index < 51 ? 'done' : 'todo',
        execution: 'idle',
        progress: { percent: index < 51 ? 100 : 0, confidence: 1, note: '' },
        assignee_agent_id: null,
        current_attempt_id: null,
        workspace_task_id: index < 51 ? `task-${String(index)}` : null,
        priority: index,
        metadata: {},
        created_at: '2026-03-30T08:00:00Z',
      })),
      counts: {},
    };
    const rootGoal: WorkspacePlanRootGoal = {
      id: 'root-task',
      title: 'Current root',
      status: 'done',
    };
    plan.nodes[51] = {
      ...plan.nodes[51],
      id: 'node-goal',
      kind: 'goal',
      title: 'Current root',
      intent: 'todo',
      workspace_task_id: null,
    };

    const stats = buildBlackboardStats(tasks, [], [], [], plan, rootGoal);

    expect(stats.totalTasks).toBe(52);
    expect(stats.completedTasks).toBe(52);
    expect(stats.todoTasks).toBe(0);
    expect(stats.inProgressTasks).toBe(0);
    expect(stats.completionRatio).toBe(100);
    expect(calculateWorkspacePlanCompletionRatio(plan, rootGoal)).toBe(stats.completionRatio);
  });

  it('builds task-board rows from current plan nodes instead of historical tasks', () => {
    const tasks: WorkspaceTask[] = [
      { ...BASE_TASK, id: 'old-done-task', status: 'done' },
      { ...BASE_TASK, id: 'stale-running-task', status: 'in_progress' },
      { ...BASE_TASK, id: 'extra-running-task', status: 'in_progress' },
    ];
    const plan: WorkspacePlan = {
      id: 'plan-current',
      workspace_id: 'ws-1',
      goal_id: 'goal-current',
      status: 'active',
      created_at: '2026-03-30T08:00:00Z',
      nodes: [
        {
          id: 'node-root',
          parent_id: null,
          kind: 'goal',
          title: 'Current root',
          description: 'Root goal',
          depends_on: [],
          acceptance_criteria: [],
          recommended_capabilities: [],
          intent: 'todo',
          execution: 'idle',
          progress: { percent: 0, confidence: 1, note: '' },
          assignee_agent_id: null,
          current_attempt_id: null,
          workspace_task_id: null,
          priority: 0,
          metadata: {},
          created_at: '2026-03-30T08:00:00Z',
        },
        {
          id: 'node-child',
          parent_id: 'node-root',
          kind: 'task',
          title: 'Current child',
          description: 'Child task',
          depends_on: [],
          acceptance_criteria: [],
          recommended_capabilities: [],
          intent: 'done',
          execution: 'idle',
          progress: { percent: 100, confidence: 1, note: '' },
          assignee_agent_id: 'agent-1',
          current_attempt_id: 'attempt-1',
          workspace_task_id: 'task-current-child',
          priority: 1,
          metadata: { iteration_index: 1 },
          created_at: '2026-03-30T08:10:00Z',
        },
      ],
      counts: {},
    };
    const rootGoal: WorkspacePlanRootGoal = {
      id: 'root-task',
      title: 'Current root',
      status: 'done',
      goal_health: 'achieved',
      remediation_status: 'none',
      evidence_grade: 'pass',
      completed_at: '2026-03-30T09:00:00Z',
    };

    const taskBoardTasks = buildBlackboardTaskBoardTasks(tasks, 'ws-1', plan, rootGoal);

    expect(taskBoardTasks).toHaveLength(2);
    expect(taskBoardTasks.map((task) => task.title)).toEqual(['Current root', 'Current child']);
    expect(taskBoardTasks.map((task) => task.status)).toEqual(['done', 'done']);
    expect(taskBoardTasks[0].metadata.source_plan_node_only).toBe(true);
    expect(taskBoardTasks[0].metadata.task_role).toBe('goal_root');
    expect(taskBoardTasks[1].id).toBe('task-current-child');
    expect(taskBoardTasks[1].metadata.source_plan_projection).toBe(true);
  });

  it('assigns fallback actor coordinates without colliding with the central blackboard', () => {
    const agents: WorkspaceAgent[] = [
      {
        id: 'agent-1',
        workspace_id: 'ws-1',
        agent_id: 'agent-alpha',
        display_name: 'Alpha',
        is_active: true,
        created_at: '2026-03-30T08:00:00Z',
      },
      {
        id: 'agent-2',
        workspace_id: 'ws-1',
        agent_id: 'agent-beta',
        display_name: 'Beta',
        is_active: false,
        hex_q: 0,
        hex_r: 0,
        created_at: '2026-03-30T08:00:00Z',
      },
    ];
    const topologyNodes: TopologyNode[] = [
      {
        id: 'human-1',
        workspace_id: 'ws-1',
        node_type: 'human_seat',
        title: 'Admin',
        position_x: 0,
        position_y: 0,
        data: {},
      },
    ];

    const actors = buildCanvasActors(agents, topologyNodes);
    const coords = actors.map((actor) => `${String(actor.q)},${String(actor.r)}`);

    expect(coords).not.toContain('0,0');
    expect(new Set(coords).size).toBe(coords.length);
    expect(actors.some((actor) => actor.kind === 'human')).toBe(true);
  });

  it('builds note cards from workspace description, objectives, and pinned posts', () => {
    const workspace: Workspace = {
      id: 'ws-1',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      name: 'Demo workspace',
      description: 'Shared operating rhythm for launch week.',
      created_by: 'user-1',
      created_at: '2026-03-30T08:00:00Z',
    };
    const objectives: CyberObjective[] = [
      {
        id: 'objective-1',
        workspace_id: 'ws-1',
        title: 'Reach launch readiness',
        obj_type: 'objective',
        progress: 80,
        created_at: '2026-03-30T08:00:00Z',
      },
    ];

    const notes = buildBlackboardNotes(workspace, objectives, [BASE_POST]);

    expect(notes[0]?.kind).toBe('workspace');
    expect(notes.some((note) => note.kind === 'objective')).toBe(true);
    expect(notes.some((note) => note.kind === 'post')).toBe(true);
  });
});
