import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  workspaceBlackboardService,
  workspacePlanService,
  workspaceService,
  workspaceTaskService,
  workspaceTopologyService,
} from '@/services/workspaceService';

vi.mock('@/i18n/config', () => ({
  default: {
    language: 'zh-CN',
    resolvedLanguage: 'zh-CN',
  },
}));

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
    vi.mocked(apiFetch.get).mockImplementationOnce(async (...args: any[]) =>
      args[1](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => ({ items: [{ id: 'ws-1', name: 'Workspace 1' }] }),
        } as Response,
        {
          signal: args[2]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceService.listByProject('tenant-1', 'project-1');

    expect(apiFetch.get).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces',
      expect.any(Function),
      {
        retry: { maxRetries: 1 },
      }
    );
    expect(result).toEqual([{ id: 'ws-1', name: 'Workspace 1' }]);
  });

  it('creates workspaces with explicit scenario and collaboration settings', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
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
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceService.create('tenant-1', 'project-1', {
      name: 'Programming Room',
      use_case: 'programming',
      collaboration_mode: 'autonomous',
      sandbox_code_root: '/workspace/my-evo',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces',
      {
        name: 'Programming Room',
        use_case: 'programming',
        collaboration_mode: 'autonomous',
        sandbox_code_root: '/workspace/my-evo',
      },
      expect.any(Function)
    );
    expect(result.metadata?.collaboration_mode).toBe('autonomous');
  });

  it('creates blackboard post for tenant/project/workspace', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 201,
          statusText: 'Created',
          headers: new Headers(),
          json: async () => ({ id: 'post-1', title: 'Design notes' }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceBlackboardService.createPost('tenant-1', 'project-1', 'ws-1', {
      title: 'Design notes',
      content: 'Initial draft',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/posts',
      {
        title: 'Design notes',
        content: 'Initial draft',
      },
      expect.any(Function)
    );
    expect(result.id).toBe('post-1');
  });

  it('lists workspace tasks via workspace scoped endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.get).mockImplementationOnce(async (...args: any[]) =>
      args[1](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => [{ id: 'task-1', title: 'Implement API', status: 'todo' }],
        } as Response,
        {
          signal: args[2]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceTaskService.list('ws-1');

    expect(apiFetch.get).toHaveBeenCalledWith('/workspaces/ws-1/tasks', expect.any(Function), {
      retry: { maxRetries: 1 },
    });
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe('Implement API');
  });

  it('assigns workspace tasks using workspace_agent_id contract', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => ({ id: 'task-1', assignee_agent_id: 'agent-1', status: 'todo' }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceTaskService.assignToAgent('ws-1', 'task-1', 'binding-1');

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/assign-agent',
      {
        workspace_agent_id: 'binding-1',
        preferred_language: 'zh-CN',
      },
      expect.any(Function)
    );
    expect(result.assignee_agent_id).toBe('agent-1');
  });

  it('creates workspace tasks with the selected UI language', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 201,
          statusText: 'Created',
          headers: new Headers(),
          json: async () => ({
            id: 'task-2',
            title: '撰写验收记录',
            metadata: { preferred_language: 'zh-CN' },
          }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceTaskService.create('ws-1', {
      title: '撰写验收记录',
      description: '补齐证据',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks',
      {
        title: '撰写验收记录',
        description: '补齐证据',
        preferred_language: 'zh-CN',
      },
      expect.any(Function)
    );
    expect(result.metadata?.preferred_language).toBe('zh-CN');
  });

  it('loads durable workspace plan snapshot via workspace scoped endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.get).mockImplementationOnce(async (...args: any[]) =>
      args[1](
        {
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
        } as Response,
        {
          signal: args[2]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.getSnapshot('ws-1', {
      outboxLimit: 8,
      eventLimit: 8,
      includeDetails: false,
      recoverStaleAttempts: false,
    });

    expect(apiFetch.get).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan?outbox_limit=8&event_limit=8&include_details=false&recover_stale_attempts=false',
      expect.any(Function),
      {
        retry: { maxRetries: 1 },
      }
    );
    expect(result.plan?.id).toBe('plan-1');
  });

  it('retries a durable workspace plan outbox item', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
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
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.retryOutboxItem('ws-1', 'outbox-1', {
      reason: 'fixed dependency',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/outbox/outbox-1/retry',
      {
        reason: 'fixed dependency',
      },
      expect.any(Function)
    );
    expect(result.outbox_id).toBe('outbox-1');
  });

  it('requests explicit durable workspace plan stale-attempt recovery', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => ({
            ok: true,
            message: 'Workspace plan stale attempt recovery queued.',
            plan_id: 'plan-1',
          }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.recoverStaleAttempts('ws-1', {
      reason: 'operator requested recovery',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/recover-stale-attempts',
      {
        reason: 'operator requested recovery',
      },
      expect.any(Function)
    );
    expect(result.plan_id).toBe('plan-1');
  });

  it('requests durable workspace plan node replan', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
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
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.requestNodeReplan('ws-1', 'node-1', {
      reason: 'scope changed',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/nodes/node-1/request-replan',
      {
        reason: 'scope changed',
      },
      expect.any(Function)
    );
    expect(result.node_id).toBe('node-1');
  });

  it('reopens a blocked durable workspace plan node', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
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
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.reopenBlockedNode('ws-1', 'node-1', {
      reason: 'operator reviewed',
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/nodes/node-1/reopen',
      {
        reason: 'operator reviewed',
      },
      expect.any(Function)
    );
    expect(result.node_id).toBe('node-1');
  });

  it('accepts a durable workspace plan node after operator review', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => ({
            ok: true,
            message: 'Plan node accepted after human review.',
            plan_id: 'plan-1',
            node_id: 'node-1',
          }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspacePlanService.acceptNodeAfterReview('ws-1', 'node-1', {
      reason: 'reviewed evidence',
      evidenceRefs: ['manual_review:ticket-1'],
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/plan/nodes/node-1/accept-review',
      {
        reason: 'reviewed evidence',
        evidence_refs: ['manual_review:ticket-1'],
      },
      expect.any(Function)
    );
    expect(result.node_id).toBe('node-1');
  });

  it('pauses, resumes, and triggers durable workspace plan iteration loop', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post)
      .mockImplementationOnce(async (...args: any[]) => args[2]({
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
      } as Response, { signal: args[3]?.signal ?? new AbortController().signal, check() { if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError'); } }))
      .mockImplementationOnce(async (...args: any[]) => args[2]({
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
      } as Response, { signal: args[3]?.signal ?? new AbortController().signal, check() { if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError'); } }))
      .mockImplementationOnce(async (...args: any[]) =>
        args[2](
          {
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
          } as Response,
          {
            signal: args[3]?.signal ?? new AbortController().signal,
            check() {
              if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
            },
          }
        )
      );

    await workspacePlanService.pauseAutoLoop('ws-1', { reason: 'operator review' });
    await workspacePlanService.resumeAutoLoop('ws-1', { reason: 'continue' });
    await workspacePlanService.triggerNextIteration('ws-1', { reason: 'manual review' });

    expect(apiFetch.post).toHaveBeenNthCalledWith(
      1,
      '/workspaces/ws-1/plan/iteration/pause',
      {
        reason: 'operator review',
      },
      expect.any(Function)
    );
    expect(apiFetch.post).toHaveBeenNthCalledWith(
      2,
      '/workspaces/ws-1/plan/iteration/resume',
      {
        reason: 'continue',
      },
      expect.any(Function)
    );
    expect(apiFetch.post).toHaveBeenNthCalledWith(
      3,
      '/workspaces/ws-1/plan/iteration/trigger-next',
      {
        reason: 'manual review',
      },
      expect.any(Function)
    );
  });

  it('updates workspace agent binding via tenant/project/workspace route', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.patch).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: new Headers(),
          json: async () => ({ id: 'binding-1', hex_q: 2, hex_r: -1 }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

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
      },
      expect.any(Function)
    );
    expect(result.hex_q).toBe(2);
  });

  it('creates topology nodes via workspace topology endpoint', async () => {
    const { apiFetch } = await import('@/services/client/urlUtils');
    vi.mocked(apiFetch.post).mockImplementationOnce(async (...args: any[]) =>
      args[2](
        {
          ok: true,
          status: 201,
          statusText: 'Created',
          headers: new Headers(),
          json: async () => ({ id: 'node-1', node_type: 'corridor', hex_q: 1, hex_r: 0 }),
        } as Response,
        {
          signal: args[3]?.signal ?? new AbortController().signal,
          check() {
            if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
          },
        }
      )
    );

    const result = await workspaceTopologyService.createNode('ws-1', {
      node_type: 'corridor',
      hex_q: 1,
      hex_r: 0,
    });

    expect(apiFetch.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/topology/nodes',
      {
        node_type: 'corridor',
        hex_q: 1,
        hex_r: 0,
      },
      expect.any(Function)
    );
    expect(result.id).toBe('node-1');
  });
});
