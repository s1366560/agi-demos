import { beforeEach, describe, expect, it, vi } from 'vitest';

import { definitionsService } from '@/services/agent/definitionsService';
import { useAgentDefinitionStore } from '@/stores/agentDefinitions';

import type { AgentDefinition } from '@/types/multiAgent';

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

const definition = (id: string, name = id) =>
  ({
    agent_to_agent_allowlist: null,
    agent_to_agent_enabled: false,
    allowed_mcp_servers: null,
    allowed_skills: null,
    allowed_tools: null,
    avg_execution_time_ms: null,
    bindings: [],
    can_spawn: false,
    created_at: '2026-06-18T00:00:00Z',
    delegate_config: null,
    discoverable: true,
    display_name: name,
    enabled: true,
    fallback_models: [],
    id,
    max_iterations: 1,
    max_retries: 0,
    max_spawn_depth: 0,
    metadata: {},
    model: null,
    name,
    persona_files: [],
    project_id: null,
    session_policy: null,
    source: 'database',
    spawn_policy: null,
    success_rate: null,
    system_prompt: null,
    temperature: null,
    tenant_id: 'tenant-1',
    tool_policy: null,
    total_invocations: 0,
    trigger: null,
    updated_at: null,
    workspace_config: null,
    workspace_dir: null,
  }) satisfies AgentDefinition;

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

  it('ignores stale responses from older definition list requests', async () => {
    const firstRequest = deferred<AgentDefinition[]>();
    vi.mocked(definitionsService.list)
      .mockReturnValueOnce(firstRequest.promise)
      .mockResolvedValueOnce([definition('definition-new', 'New definition')]);

    const firstLoad = useAgentDefinitionStore
      .getState()
      .listDefinitions({ tenant_id: 'tenant-old' });
    const secondLoad = useAgentDefinitionStore
      .getState()
      .listDefinitions({ tenant_id: 'tenant-new' });

    await secondLoad;
    firstRequest.resolve([definition('definition-old', 'Old definition')]);
    await firstLoad;

    const state = useAgentDefinitionStore.getState();
    expect(state.definitions).toEqual([expect.objectContaining({ id: 'definition-new' })]);
    expect(state.total).toBe(1);
    expect(state.isLoading).toBe(false);
  });

  it('ignores definition list responses that resolve after reset', async () => {
    const request = deferred<AgentDefinition[]>();
    vi.mocked(definitionsService.list).mockReturnValueOnce(request.promise);

    const load = useAgentDefinitionStore.getState().listDefinitions({ tenant_id: 'tenant-1' });

    useAgentDefinitionStore.getState().reset();
    request.resolve([definition('definition-stale', 'Stale definition')]);
    await load;

    const state = useAgentDefinitionStore.getState();
    expect(state.definitions).toEqual([]);
    expect(state.total).toBe(0);
    expect(state.isLoading).toBe(false);
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
