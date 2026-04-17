import { describe, expect, it } from 'vitest';

import {
  buildBlackboardNotes,
  buildBlackboardStats,
  buildCanvasActors,
  groupTasksByStatus,
} from '@/components/blackboard/blackboardUtils';

import type {
  BlackboardPost,
  CyberObjective,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
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
