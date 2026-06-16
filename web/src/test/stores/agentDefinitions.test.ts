import { beforeEach, describe, expect, it, vi } from 'vitest';

import { definitionsService } from '@/services/agent/definitionsService';
import { useAgentDefinitionStore } from '@/stores/agentDefinitions';

vi.mock('@/services/agent/definitionsService', () => ({
  definitionsService: {
    list: vi.fn(),
    listPage: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    setEnabled: vi.fn(),
  },
}));

describe('agent definition store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentDefinitionStore.getState().reset();
    vi.mocked(definitionsService.list).mockResolvedValue([]);
  });

  it('preserves explicit enabled-only requests when listing definitions', async () => {
    useAgentDefinitionStore.getState().setFilters({
      search: 'disabled search',
      enabled: false,
      projectId: null,
    });

    await useAgentDefinitionStore.getState().listDefinitions({
      enabled_only: true,
      project_id: 'project-1',
    });

    expect(definitionsService.list).toHaveBeenCalledWith({
      enabled_only: true,
      project_id: 'project-1',
    });
  });

  it('keeps explicit enabled filters from being converted to enabled-only requests', async () => {
    useAgentDefinitionStore.getState().setFilters({
      search: '',
      enabled: true,
      projectId: null,
    });

    await useAgentDefinitionStore.getState().listDefinitions({ enabled: false });

    expect(definitionsService.list).toHaveBeenCalledWith({
      enabled: false,
      project_id: undefined,
      enabled_only: undefined,
    });
  });

  it('passes selected tenant options to definition actions', async () => {
    vi.mocked(definitionsService.setEnabled).mockResolvedValue({
      id: 'agent-1',
      enabled: false,
    } as never);

    await useAgentDefinitionStore
      .getState()
      .toggleEnabled('agent-1', false, { tenant_id: 'tenant-1' });

    expect(definitionsService.setEnabled).toHaveBeenCalledWith('agent-1', false, {
      tenant_id: 'tenant-1',
    });
  });
});
