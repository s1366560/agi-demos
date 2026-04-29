import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  workspaceBlackboardService,
  workspacePlanService,
  workspaceService,
  workspaceTaskService,
  workspaceTopologyService,
} from '@/services/workspaceService';

vi.mock('@/services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('workspaceService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists project workspaces with tenant/project scope', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({ items: [{ id: 'ws-1', name: 'Workspace 1' }] }),
    } as Response);

    const result = await workspaceService.listByProject('tenant-1', 'project-1');

    expect(apiFetch.get).toHaveBeenCalledWith('/tenants/tenant-1/projects/project-1/workspaces', {
      retry: { maxRetries: 1 },
    });
    expect(result).toEqual([{ id: 'ws-1', name: 'Workspace 1' }]);
  });

  it('creates workspaces with explicit scenario and collaboration settings', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 201,
      statusText: 'Created',
      headers: new Headers(),
      json: async () => ({
        id: 'ws-2',
        name: 'Programming Room',
        metadata: {
          workspace_use_case: 'programming',
          workspace_type: 'software_development',
          collaboration_mode: 'autonomous',
        },
      }),
    } as Response);

    const result = await workspaceService.create('tenant-1', 'project-1', {
      name: 'Programming Room',
      use_case: 'programming',
      collaboration_mode: 'autonomous',
      sandbox_code_root: '/workspace/my-evo',
    });

    expect(apiFetch.post).toHaveBeenCalledWith('/tenants/tenant-1/projects/project-1/workspaces', {
      name: 'Programming Room',
      use_case: 'programming',
      collaboration_mode: 'autonomous',
      sandbox_code_root: '/workspace/my-evo',
    });
    expect(result.metadata?.collaboration_mode).toBe('autonomous');
  });

  it('creates blackboard post for tenant/project/workspace', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 201,
      statusText: 'Created',
      headers: new Headers(),
      json: async () => ({ id: 'post-1', title: 'Design notes' }),
    } as Response);

    const result = await workspaceBlackboardService.createPost('tenant-1', 'project-1', 'ws-1', {
      title: 'Design notes',
      content: 'Initial draft',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/posts',
      {
        title: 'Design notes',
        content: 'Initial draft',
      }
    );
    expect(result.id).toBe('post-1');
  });

  it('lists workspace tasks via workspace scoped endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => [{ id: 'task-1', title: 'Implement API', status: 'todo' }],
    } as Response);

    const result = await workspaceTaskService.list('ws-1');

    expect(apiFetch.get).toHaveBeenCalledWith('/workspaces/ws-1/tasks', {
      retry: { maxRetries: 1 },
    });
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe('Implement API');
  });

  it('assigns workspace tasks using workspace_agent_id contract', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({ id: 'task-1', assignee_agent_id: 'agent-1', status: 'todo' }),
    } as Response);

    const result = await workspaceTaskService.assignToAgent('ws-1', 'task-1', 'binding-1');

    expect(apiFetch.post).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/assign-agent', {
      workspace_agent_id: 'binding-1',
    });
    expect(result.assignee_agent_id).toBe('agent-1');
  });

  it('loads durable workspace plan snapshot via workspace scoped endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.get).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({
        workspace_id: 'ws-1',
        plan: { id: 'plan-1', workspace_id: 'ws-1', goal_id: 'goal-1', status: 'active' },
        blackboard: [],
        outbox: [],
        events: [],
      }),
    } as Response);

    const result = await workspacePlanService.getSnapshot('ws-1', {
      outboxLimit: 8,
      eventLimit: 8,
    });

    expect(apiFetch.get).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan?outbox_limit=8&event_limit=8',
      {
        retry: { maxRetries: 1 },
      }
    );
    expect(result.plan?.id).toBe('plan-1');
  });

  it('retries a durable workspace plan outbox item', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({
        ok: true,
        message: 'Outbox job queued for retry.',
        plan_id: 'plan-1',
        outbox_id: 'outbox-1',
      }),
    } as Response);

    const result = await workspacePlanService.retryOutboxItem('ws-1', 'outbox-1', {
      reason: 'fixed dependency',
    });

    expect(apiFetch.post).toHaveBeenCalledWith('/workspaces/ws-1/plan/outbox/outbox-1/retry', {
      reason: 'fixed dependency',
    });
    expect(result.outbox_id).toBe('outbox-1');
  });

  it('requests durable workspace plan node replan', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({
        ok: true,
        message: 'Plan node sent back for supervisor recovery.',
        plan_id: 'plan-1',
        node_id: 'node-1',
      }),
    } as Response);

    const result = await workspacePlanService.requestNodeReplan('ws-1', 'node-1', {
      reason: 'scope changed',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/nodes/node-1/request-replan',
      {
        reason: 'scope changed',
      }
    );
    expect(result.node_id).toBe('node-1');
  });

  it('reopens a blocked durable workspace plan node', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({
        ok: true,
        message: 'Blocked plan node reopened.',
        plan_id: 'plan-1',
        node_id: 'node-1',
      }),
    } as Response);

    const result = await workspacePlanService.reopenBlockedNode('ws-1', 'node-1', {
      reason: 'operator reviewed',
    });

    expect(apiFetch.post).toHaveBeenCalledWith('/workspaces/ws-1/plan/nodes/node-1/reopen', {
      reason: 'operator reviewed',
    });
    expect(result.node_id).toBe('node-1');
  });

  it('pauses, resumes, and triggers durable workspace plan iteration loop', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: async () => ({
          ok: true,
          message: 'Automatic iteration loop paused.',
          plan_id: 'plan-1',
          node_id: 'goal-1',
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: async () => ({
          ok: true,
          message: 'Automatic iteration loop resumed.',
          plan_id: 'plan-1',
          node_id: 'goal-1',
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: async () => ({
          ok: true,
          message: 'Next iteration review requested.',
          plan_id: 'plan-1',
          node_id: 'goal-1',
        }),
      } as Response);

    await workspacePlanService.pauseAutoLoop('ws-1', { reason: 'operator review' });
    await workspacePlanService.resumeAutoLoop('ws-1', { reason: 'continue' });
    await workspacePlanService.triggerNextIteration('ws-1', { reason: 'manual review' });

    expect(apiFetch.post).toHaveBeenNthCalledWith(1, '/workspaces/ws-1/plan/iteration/pause', {
      reason: 'operator review',
    });
    expect(apiFetch.post).toHaveBeenNthCalledWith(2, '/workspaces/ws-1/plan/iteration/resume', {
      reason: 'continue',
    });
    expect(apiFetch.post).toHaveBeenNthCalledWith(
      3,
      '/workspaces/ws-1/plan/iteration/trigger-next',
      {
        reason: 'manual review',
      }
    );
  });

  it('updates workspace agent binding via tenant/project/workspace route', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.patch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => ({ id: 'binding-1', hex_q: 2, hex_r: -1 }),
    } as Response);

    const result = await workspaceService.updateAgentBinding(
      'tenant-1',
      'project-1',
      'ws-1',
      'binding-1',
      {
        hex_q: 2,
        hex_r: -1,
      }
    );

    expect(apiFetch.patch).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents/binding-1',
      {
        hex_q: 2,
        hex_r: -1,
      }
    );
    expect(result.hex_q).toBe(2);
  });

  it('creates topology nodes via workspace topology endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockResolvedValueOnce({
      ok: true,
      status: 201,
      statusText: 'Created',
      headers: new Headers(),
      json: async () => ({ id: 'node-1', node_type: 'corridor', hex_q: 1, hex_r: 0 }),
    } as Response);

    const result = await workspaceTopologyService.createNode('ws-1', {
      node_type: 'corridor',
      hex_q: 1,
      hex_r: 0,
    });

    expect(apiFetch.post).toHaveBeenCalledWith('/workspaces/ws-1/topology/nodes', {
      node_type: 'corridor',
      hex_q: 1,
      hex_r: 0,
    });
    expect(result.id).toBe('node-1');
  });
});
