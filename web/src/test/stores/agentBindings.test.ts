import { beforeEach, describe, expect, it, vi } from 'vitest';

import { bindingsService } from '@/services/agent/bindingsService';
import { useAgentBindingStore } from '@/stores/agentBindings';

vi.mock('@/services/agent/bindingsService', () => ({
  bindingsService: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    setEnabled: vi.fn(),
    test: vi.fn(),
  },
}));

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
