import { beforeEach, describe, expect, it, vi } from 'vitest';

import { subagentAPI } from '@/services/subagentService';
import { useSubAgentStore } from '@/stores/subagent';

import type { SubAgentResponse } from '@/types/agent';

vi.mock('@/services/subagentService', () => ({
  subagentAPI: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    setEnabled: vi.fn(),
    listTemplates: vi.fn(),
    createFromTemplate: vi.fn(),
    importFilesystem: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

const subagent = (id: string, name = id) =>
  ({
    allowed_mcp_servers: [],
    allowed_skills: [],
    allowed_tools: [],
    avg_execution_time_ms: 0,
    color: '#1e3fae',
    created_at: '2026-06-18T00:00:00Z',
    display_name: name,
    enabled: true,
    id,
    max_iterations: 1,
    max_tokens: 1024,
    model: 'gpt-test',
    name,
    project_id: null,
    success_rate: 0,
    system_prompt: 'You are a test subagent.',
    temperature: 0,
    tenant_id: 'tenant-1',
    total_invocations: 0,
    trigger: {
      description: 'Test trigger',
      examples: [],
      keywords: [],
    },
    updated_at: '2026-06-18T00:00:00Z',
  }) satisfies SubAgentResponse;

describe('subagent store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSubAgentStore.getState().reset();
    vi.mocked(subagentAPI.list).mockResolvedValue({ subagents: [], total: 0 });
  });

  it('coalesces concurrent subagent list requests with matching params', async () => {
    const request = deferred<{ subagents: SubAgentResponse[]; total: number }>();
    vi.mocked(subagentAPI.list).mockReturnValueOnce(request.promise);

    const firstLoad = useSubAgentStore
      .getState()
      .listSubAgents({ tenant_id: 'tenant-1', enabled_only: true, limit: 20 });
    const secondLoad = useSubAgentStore
      .getState()
      .listSubAgents({ enabled_only: true, limit: 20, tenant_id: 'tenant-1' });

    expect(subagentAPI.list).toHaveBeenCalledTimes(1);

    request.resolve({ subagents: [subagent('subagent-1', 'Subagent 1')], total: 1 });
    await Promise.all([firstLoad, secondLoad]);

    const state = useSubAgentStore.getState();
    expect(state.subagents).toEqual([expect.objectContaining({ id: 'subagent-1' })]);
    expect(state.total).toBe(1);
    expect(state.isLoading).toBe(false);
  });
});
