import { beforeEach, describe, expect, it, vi } from 'vitest';

import { bindingsService } from '@/services/agent/bindingsService';
import { useAgentBindingStore } from '@/stores/agentBindings';

import type { AgentBinding } from '@/types/multiAgent';

vi.mock('@/services/agent/bindingsService', () => ({
  bindingsService: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    setEnabled: vi.fn(),
    test: vi.fn(),
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

const binding = (id: string): AgentBinding => ({
  account_id: null,
  agent_id: 'agent-1',
  channel_id: null,
  channel_type: null,
  created_at: '2026-06-18T00:00:00Z',
  enabled: true,
  group_id: null,
  id,
  peer_id: null,
  priority: 0,
  specificity_score: 0,
  tenant_id: 'tenant-1',
});

describe('agent binding store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentBindingStore.getState().reset();
    vi.mocked(bindingsService.list).mockResolvedValue([]);
  });

  it('passes selected tenant when listing bindings', async () => {
    await useAgentBindingStore.getState().listBindings({
      tenant_id: 'tenant-1',
      agent_id: 'agent-1',
      enabled_only: true,
    });

    expect(bindingsService.list).toHaveBeenCalledWith({
      tenant_id: 'tenant-1',
      agent_id: 'agent-1',
      enabled_only: true,
    });
  });

  it('preserves explicit enabled filters over store filters', async () => {
    useAgentBindingStore.getState().setFilters({
      enabledOnly: true,
    });

    await useAgentBindingStore.getState().listBindings({ enabled_only: false });

    expect(bindingsService.list).toHaveBeenCalledWith({
      tenant_id: undefined,
      agent_id: undefined,
      enabled_only: false,
    });
  });

  it('ignores stale responses from older binding list requests', async () => {
    const firstRequest = deferred<AgentBinding[]>();
    vi.mocked(bindingsService.list)
      .mockReturnValueOnce(firstRequest.promise)
      .mockResolvedValueOnce([binding('binding-new')]);

    const firstLoad = useAgentBindingStore.getState().listBindings({ tenant_id: 'tenant-old' });
    const secondLoad = useAgentBindingStore.getState().listBindings({ tenant_id: 'tenant-new' });

    await secondLoad;
    firstRequest.resolve([binding('binding-old')]);
    await firstLoad;

    const state = useAgentBindingStore.getState();
    expect(state.bindings).toEqual([expect.objectContaining({ id: 'binding-new' })]);
    expect(state.isLoading).toBe(false);
  });

  it('ignores binding list responses that resolve after reset', async () => {
    const request = deferred<AgentBinding[]>();
    vi.mocked(bindingsService.list).mockReturnValueOnce(request.promise);

    const load = useAgentBindingStore.getState().listBindings({ tenant_id: 'tenant-1' });

    useAgentBindingStore.getState().reset();
    request.resolve([binding('binding-stale')]);
    await load;

    const state = useAgentBindingStore.getState();
    expect(state.bindings).toEqual([]);
    expect(state.isLoading).toBe(false);
  });

  it('passes selected tenant options to binding actions', async () => {
    vi.mocked(bindingsService.setEnabled).mockResolvedValue({
      id: 'binding-1',
      enabled: false,
    } as never);

    await useAgentBindingStore
      .getState()
      .toggleBinding('binding-1', false, { tenant_id: 'tenant-1' });

    expect(bindingsService.setEnabled).toHaveBeenCalledWith('binding-1', false, {
      tenant_id: 'tenant-1',
    });
  });
});
