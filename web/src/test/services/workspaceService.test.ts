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
