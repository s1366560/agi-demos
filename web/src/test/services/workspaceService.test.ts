import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  workspaceBlackboardService,
  workspaceService,
  workspaceTaskService,
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

    expect(apiFetch.get).toHaveBeenCalledWith('/tenants/tenant-1/projects/project-1/workspaces/', {
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

    expect(apiFetch.get).toHaveBeenCalledWith('/workspaces/ws-1/tasks/', {
      retry: { maxRetries: 1 },
    });
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe('Implement API');
  });
});
